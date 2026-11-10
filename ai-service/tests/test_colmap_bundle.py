"""
Bundled COLMAP 1.0 (no CUDA): locator, runtime environment, loader-failure messages, database validation, and a check of every
flag we emit against the option names that exist inside the real colmap.exe.

What this proves and what it does not:
  * the flag-vs-binary test reads the bytes of tools/colmap/bin/colmap.exe and requires each emitted option name to be present in
    the binary. That rules out "Unrecognised option" for names that do not exist at all. It cannot prove which command owns an option
    (that is read from `colmap <cmd> -h` at run time on Windows) and it does not execute the binary (impossible on Linux).
"""
import os
import sqlite3
import stat
import sys

import pytest

from app import colmap_compat as cc
from app import colmap_locator as loc
from app import colmap_validate as val
from app import config
from app.errors import PipelineError

# Option names COLMAP 1.0 lists, as found in colmap.exe (feature extraction renamed Sift* -> Feature* for use_gpu/max_image_size)
REAL = {
    "feature_extractor": ["database_path", "image_path", "ImageReader.single_camera", "ImageReader.camera_model",
                          "FeatureExtraction.use_gpu", "FeatureExtraction.max_image_size", "FeatureExtraction.num_threads",
                          "SiftExtraction.max_num_features"],
    "exhaustive_matcher": ["database_path", "FeatureMatching.use_gpu", "FeatureMatching.num_threads"],
    "sequential_matcher": ["database_path", "FeatureMatching.use_gpu", "FeatureMatching.num_threads", "SequentialMatching.overlap",
                           "SequentialMatching.loop_detection", "SequentialMatching.vocab_tree_path"],
    "mapper": ["database_path", "image_path", "output_path", "Mapper.num_threads", "Mapper.ba_use_gpu"],
    "model_converter": ["input_path", "output_path", "output_type"],
    "bundle_adjuster": ["input_path", "output_path"],
    "image_undistorter": ["image_path", "input_path", "output_path", "output_type"],
    "patch_match_stereo": ["workspace_path", "PatchMatchStereo.max_image_size", "PatchMatchStereo.num_threads"],
    "stereo_fusion": ["workspace_path", "output_path", "StereoFusion.max_image_size", "StereoFusion.num_threads"],
}


def _caps(cuda=False):
    return cc.ColmapCaps("colmap.exe", "1.0.0", {k: set(v) for k, v in REAL.items()}, banner="COLMAP 1.0.0 without CUDA", cuda=cuda)


def _bundled():
    exe = loc.bundled_dir() / "bin" / "colmap.exe"
    return exe if exe.is_file() else None


# ---- locator -----------------------------------------------------------------------------------------------------------

def test_override_beats_bundle_and_path(tmp_path, monkeypatch):
    exe = tmp_path / "mine" / "colmap"
    exe.parent.mkdir()
    exe.write_text("x")
    monkeypatch.setattr(config, "COLMAP_BIN", str(exe))
    r = loc.locate()
    assert r.source == "override" and r.path == str(exe.resolve())


def test_override_may_be_a_folder(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / loc.EXE).write_text("x")
    monkeypatch.setattr(config, "COLMAP_BIN", str(tmp_path))
    assert loc.locate().source == "override"


def test_bundled_build_is_found_by_default(tmp_path, monkeypatch):
    b = tmp_path / "tools" / "colmap" / "bin"
    b.mkdir(parents=True)
    (b / loc.EXE).write_text("x")
    monkeypatch.setenv("COLMAP_BUNDLE_DIR", str(tmp_path / "tools" / "colmap"))
    monkeypatch.setattr(config, "COLMAP_BIN", "")
    r = loc.locate()
    assert r.source == "bundled" and r.bin_dir == str(b.resolve())


def test_not_found_lists_where_it_looked(tmp_path, monkeypatch):
    monkeypatch.setenv("COLMAP_BUNDLE_DIR", str(tmp_path / "nothing"))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(config, "COLMAP_BIN", "")
    r = loc.locate()
    assert not r.found and r.source == "none" and any("bundled" in t for t in r.tried)


def test_runtime_env_puts_colmap_bin_first_on_path(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "plugins").mkdir()
    env = loc.runtime_env(tmp_path / "bin", base={"PATH": "C:\\Windows"})
    assert env["PATH"].startswith(str(tmp_path / "bin")) and env["QT_QPA_PLATFORM"] == "offscreen"
    assert env["QT_PLUGIN_PATH"] == str(tmp_path / "plugins")


def test_loader_failures_are_explained():
    assert "Visual C++" in loc.describe_exit(3221225781)
    assert "0xC000007B" in loc.describe_exit(3221225595)
    assert loc.describe_exit(1) is None and loc.describe_exit(0) is None


def test_bundle_report_counts_dlls(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    for n in ("Qt6Core.dll", "ceres.dll", "boost_thread-vc145-mt-x64-1_92.dll", "OpenImageIO.dll"):
        (b / n).write_text("x")
    (b / loc.EXE).write_text("x")
    monkeypatch.setenv("COLMAP_BUNDLE_DIR", str(tmp_path))
    r = loc.bundle_report()
    assert r["exe_present"] and r["dll_count"] == 4 and r["has_core_dlls"]


# ---- caps: CUDA and dense MVS --------------------------------------------------------------------------------------------

def test_cuda_parsing():
    assert cc.parse_cuda("COLMAP 1.0.0 -- x (Commit abc, without CUDA)") is False
    assert cc.parse_cuda("COLMAP 3.9 with CUDA") is True
    assert cc.parse_cuda("COLMAP 1.0.0") is None


def test_no_cuda_build_refuses_patch_match_with_reason():
    sup = cc.dense_mvs_support(_caps(cuda=False))
    assert not sup["supported"] and "CUDA" in sup["reason"] and "Open3D" in sup["reason"]
    with pytest.raises(cc.ColmapCompatError, match="CUDA"):
        cc.build_patch_match(_caps(False), workspace="w", max_image_size=800, threads=2)
    with pytest.raises(cc.ColmapCompatError, match="CUDA"):
        cc.build_stereo_fusion(_caps(False), workspace="w", out_ply="o.ply", max_image_size=800, threads=2)


def test_unknown_cuda_state_is_treated_as_cpu_only():
    assert not cc.dense_mvs_support(_caps(cuda=None))["supported"]


def test_cuda_build_builds_dense_commands_from_listed_options():
    caps = _caps(cuda=True)
    pm = cc.build_patch_match(caps, workspace="w", max_image_size=800, threads=2)
    assert pm[1] == "patch_match_stereo" and "--PatchMatchStereo.max_image_size" in pm
    sf = cc.build_stereo_fusion(caps, workspace="w", out_ply="o.ply", max_image_size=800, threads=2)
    assert sf[sf.index("--output_path") + 1] == "o.ply"
    ud = cc.build_undistorter(caps, images="i", sparse_model="m", out_dir="o", max_image_size=800)
    assert ud[1] == "image_undistorter" and "--max_image_size" not in ud   # not listed -> not passed


def test_bundle_adjuster_uses_only_listed_flags():
    argv = cc.build_bundle_adjuster(_caps(), model_in="a", model_out="b")
    assert {a[2:] for a in argv if a.startswith("--")} <= set(REAL["bundle_adjuster"])


def test_loop_closure_only_with_an_existing_vocab_file(tmp_path, monkeypatch):
    kw = dict(db="d.db", images="i", sparse="s", max_image_size=960, max_features=4000, threads=3, n_images=400, exhaustive_limit=120, overlap=12)
    off = dict(cc.build_commands(_caps(), **kw).commands)["sequential_matcher"]
    assert off[off.index("--SequentialMatching.loop_detection") + 1] == "0"
    vt = tmp_path / "vocab.bin"
    vt.write_text("x")
    monkeypatch.setattr(config, "COLMAP_VOCAB_TREE", str(vt))
    on = dict(cc.build_commands(_caps(), **kw).commands)["sequential_matcher"]
    assert on[on.index("--SequentialMatching.loop_detection") + 1] == "1" and str(vt) in on


# ---- flags against the real binary ---------------------------------------------------------------------------------------

def test_every_emitted_flag_exists_inside_the_real_colmap_exe():
    exe = _bundled()
    if exe is None:
        pytest.skip("tools/colmap/bin/colmap.exe not present")
    data = exe.read_bytes()
    caps = _caps(cuda=True)
    emitted = set()
    for n in (20, 400):
        cs = cc.build_commands(caps, db="d", images="i", sparse="s", max_image_size=960, max_features=4000, threads=3, n_images=n,
                               exhaustive_limit=120, overlap=12)
        for _, argv in cs.commands:
            emitted |= {a[2:] for a in argv if a.startswith("--")}
    emitted |= {a[2:] for a in cc.build_patch_match(caps, workspace="w", max_image_size=1, threads=1) if a.startswith("--")}
    emitted |= {a[2:] for a in cc.build_stereo_fusion(caps, workspace="w", out_ply="o", max_image_size=1, threads=1) if a.startswith("--")}
    missing = sorted(f for f in emitted if f.encode() not in data)
    assert not missing, f"option names not present anywhere in colmap.exe: {missing}"
    assert b"SiftExtraction.max_image_size" not in data    # the old spelling that caused the reported error is gone from this build
    assert b"FeatureExtraction.max_image_size" in data


# ---- database validation -------------------------------------------------------------------------------------------------

def _db(path, images=10, kp_rows=500, kp_images=None, pairs=10):
    con = sqlite3.connect(path)
    con.execute("create table images (image_id integer)")
    con.execute("create table keypoints (image_id integer, rows integer, cols integer, data blob)")
    con.execute("create table two_view_geometries (pair_id integer, rows integer, cols integer, data blob, config integer)")
    for i in range(images):
        con.execute("insert into images values (?)", (i,))
    for i in range(images if kp_images is None else kp_images):
        con.execute("insert into keypoints values (?,?,2,x'00')", (i, kp_rows))
    for i in range(pairs):
        con.execute("insert into two_view_geometries values (?,20,2,x'00',2)", (i,))
    con.commit()
    con.close()


def test_features_pass_with_enough_keypoints(tmp_path):
    _db(tmp_path / "d.db")
    info = val.validate_features(tmp_path / "d.db", 10)
    assert info["images_with_keypoints"] == 10 and info["average_keypoints_per_image"] == 500


def test_features_fail_on_missing_db_and_on_empty_frames(tmp_path):
    with pytest.raises(PipelineError, match="no database"):
        val.validate_features(tmp_path / "none.db", 10)
    _db(tmp_path / "a.db", kp_images=3)
    with pytest.raises(PipelineError, match="only 3 of 10"):
        val.validate_features(tmp_path / "a.db", 10)
    _db(tmp_path / "b.db", kp_rows=10)
    with pytest.raises(PipelineError, match="keypoints per frame"):
        val.validate_features(tmp_path / "b.db", 10)


def test_matches_fail_when_nothing_verified(tmp_path):
    _db(tmp_path / "d.db", pairs=0)
    with pytest.raises(PipelineError, match="verified only 0"):
        val.validate_matches(tmp_path / "d.db", 20)
    _db(tmp_path / "e.db", pairs=9)
    assert val.validate_matches(tmp_path / "e.db", 20)["verified_pairs"] == 9


def test_validation_never_modifies_the_database(tmp_path):
    _db(tmp_path / "d.db")
    before = (tmp_path / "d.db").read_bytes()
    val.inspect_database(tmp_path / "d.db")
    assert (tmp_path / "d.db").read_bytes() == before
