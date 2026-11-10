"""
COLMAP command construction, tested against help texts and a stand-in executable.

These tests prove the *logic* (probe -> choose supported spellings -> build argv -> run -> retry/cleanup). They do not
prove that a real COLMAP 4.2.1 accepts the arguments: that is checked by tools/cpu_acceptance.py on the target machine,
which reads the real `-h` output of the installed binary.
"""
import json
import os
import stat
import subprocess
import sys
import textwrap

import cv2
import numpy as np
import pytest

from app import colmap_compat as cc
from app import config, jobs, memory_plan, reconstruct
from app.errors import PipelineError

NEW = {  # option spellings listed by the 4.x line (verified against pycolmap 4.2.1's option classes)
    "feature_extractor": ["database_path", "image_path", "ImageReader.single_camera", "ImageReader.camera_model",
                          "FeatureExtraction.use_gpu", "FeatureExtraction.max_image_size", "FeatureExtraction.num_threads",
                          "SiftExtraction.max_num_features"],
    "exhaustive_matcher": ["database_path", "FeatureMatching.use_gpu", "FeatureMatching.num_threads"],
    "sequential_matcher": ["database_path", "FeatureMatching.use_gpu", "FeatureMatching.num_threads",
                           "SequentialMatching.overlap", "SequentialMatching.loop_detection"],
    "mapper": ["database_path", "image_path", "output_path", "Mapper.num_threads", "Mapper.ba_use_gpu"],
    "model_converter": ["input_path", "output_path", "output_type"],
}
OLD = {k: [o.replace("FeatureExtraction.", "SiftExtraction.").replace("FeatureMatching.", "SiftMatching.") for o in v]
       for k, v in NEW.items()}

FAKE = textwrap.dedent('''\
    #!{py}
    import json, os, sys
    from pathlib import Path
    spec = json.loads(os.environ["FAKE_SPEC"])
    argv = sys.argv[1:]
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(argv) + "\\n")
    if argv[:1] == ["help"]:
        print("COLMAP 4.2.1 -- Structure-from-Motion and Multi-View Stereo"); sys.exit(0)
    if len(argv) == 2 and argv[1] == "-h":
        print("Options:"); [print("  --%s arg" % o) for o in spec.get(argv[0], [])]; sys.exit(0)
    cmd = argv[0]
    if cmd in ("feature_extractor", "exhaustive_matcher", "sequential_matcher"):
        import sqlite3
        con = sqlite3.connect(argv[argv.index("--database_path") + 1])
        if cmd == "feature_extractor":
            n = len(os.listdir(argv[argv.index("--image_path") + 1]))
            con.execute("create table if not exists images (image_id integer)")
            con.execute("create table if not exists keypoints (image_id integer, rows integer, cols integer, data blob)")
            for i in range(n):
                con.execute("insert into images values (?)", (i + 1,))
                con.execute("insert into keypoints values (?, 500, 2, x'00')", (i + 1,))
        else:
            con.execute("create table if not exists two_view_geometries (pair_id integer, rows integer, cols integer, data blob, config integer)")
            for i in range(200):
                con.execute("insert into two_view_geometries values (?, 30, 2, x'00', 2)", (i,))
        con.commit(); con.close()
    if cmd == "mapper":
        flag = Path(os.environ["FAKE_OOM_FLAG"])
        if os.environ.get("FAKE_OOM") == "always" or (os.environ.get("FAKE_OOM") == "once" and not flag.exists()):
            flag.write_text("x"); sys.stderr.write("std::bad_alloc"); sys.exit(137)
        out = Path(argv[argv.index("--output_path") + 1]) / "0"; out.mkdir(parents=True)
        (out / "marker").write_text("m")
    if cmd == "model_converter":
        o = Path(argv[argv.index("--output_path") + 1])
        n = int(os.environ.get("FAKE_REGISTERED", "8"))
        (o / "cameras.txt").write_text("1 SIMPLE_RADIAL 480 360 420 240 180 0\\n")
        lines = []
        for i in range(n):
            lines.append("%d 1 0 0 0 %f 0 0 1 f_%06d.jpg" % (i + 1, -0.3 * i, i)); lines.append("")
        (o / "images.txt").write_text("\\n".join(lines) + "\\n")
        rng = __import__("random").Random(1)
        (o / "points3D.txt").write_text("\\n".join("%d %f %f %f 10 20 30 0.5 1 1 2 2 3 3" % (i, rng.random() * 3, rng.random() * 2, 3 + rng.random() * 3) for i in range(80)))
    sys.exit(0)
''')


@pytest.fixture
def fake(tmp_path, monkeypatch):
    def make(spec, oom=None, registered=8):
        exe = tmp_path / ("colmap.py" if os.name == "nt" else "colmap")
        exe.write_text(FAKE.format(py=sys.executable))
        if os.name != "nt":
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        else:
            real_run, real_popen = subprocess.run, subprocess.Popen

            def command_args(args):
                if args and str(args[0]) == str(exe):
                    return [sys.executable, str(exe), *args[1:]]
                return args

            monkeypatch.setattr(subprocess, "run", lambda args, *a, **kw: real_run(command_args(args), *a, **kw))
            monkeypatch.setattr(subprocess, "Popen", lambda args, *a, **kw: real_popen(command_args(args), *a, **kw))
        log = tmp_path / "calls.log"
        monkeypatch.setenv("FAKE_SPEC", json.dumps(spec))
        monkeypatch.setenv("FAKE_LOG", str(log))
        monkeypatch.setenv("FAKE_OOM_FLAG", str(tmp_path / "oom.flag"))
        monkeypatch.setenv("FAKE_REGISTERED", str(registered))
        if oom:
            monkeypatch.setenv("FAKE_OOM", oom)
        cc.clear_cache()
        return str(exe), log
    return make


def _calls(log):
    return [json.loads(x) for x in log.read_text().splitlines()]


def _build(caps, n=20, **kw):
    args = dict(db="d.db", images="img", sparse="sp", max_image_size=960, max_features=4000, threads=3, n_images=n,
                exhaustive_limit=120, overlap=12)
    args.update(kw)
    return cc.build_commands(caps, **args)


def _caps(spec):
    return cc.ColmapCaps("colmap", "4.2.1", {k: set(v) for k, v in spec.items()})


# ---- parsing -------------------------------------------------------------------------------------------------------

def test_parse_help_and_version():
    text = "COLMAP 4.2.1 -- Structure-from-Motion\n  -h [ --help ]\n  --FeatureExtraction.use_gpu arg (=1)\n  --database_path arg\n"
    assert cc.parse_version(text) == "4.2.1"
    assert cc.parse_help(text) == {"FeatureExtraction.use_gpu", "database_path"}
    assert "help" not in cc.parse_help(text)


# ---- command construction ------------------------------------------------------------------------------------------

def test_new_names_are_used_and_gpu_is_forced_off():
    cs = _build(_caps(NEW))
    fe = dict(cs.commands)["feature_extractor"]
    assert fe[fe.index("--FeatureExtraction.use_gpu") + 1] == "0"
    assert fe[fe.index("--FeatureExtraction.max_image_size") + 1] == "960"
    assert "--SiftExtraction.use_gpu" not in fe and "--SiftExtraction.max_image_size" not in fe
    m = dict(cs.commands)["exhaustive_matcher"]
    assert m[m.index("--FeatureMatching.use_gpu") + 1] == "0"
    assert not [c for c in cs.commands if c[0] == "sequential_matcher"]


def test_old_names_are_used_for_old_colmap():
    cs = _build(_caps(OLD))
    fe = dict(cs.commands)["feature_extractor"]
    assert "--SiftExtraction.use_gpu" in fe and "--SiftExtraction.max_image_size" in fe
    assert "--FeatureExtraction.use_gpu" not in fe
    assert "--SiftMatching.use_gpu" in dict(cs.commands)["exhaustive_matcher"]


def test_every_flag_passed_is_listed_by_the_binary():
    for spec in (NEW, OLD):
        for n in (20, 400):
            caps = _caps(spec)
            for label, argv in _build(caps, n=n).commands:
                flags = [a[2:] for a in argv if a.startswith("--")]
                assert set(flags) <= caps.options[label], (label, set(flags) - caps.options[label])


def test_large_sets_use_sequential_matching_with_overlap():
    cs = _build(_caps(NEW), n=400, overlap=10)
    names = [c[0] for c in cs.commands]
    assert names == ["feature_extractor", "sequential_matcher", "mapper"]
    seq = dict(cs.commands)["sequential_matcher"]
    assert seq[seq.index("--SequentialMatching.overlap") + 1] == "10"
    assert seq[seq.index("--SequentialMatching.loop_detection") + 1] == "0"


def test_required_option_missing_gives_informative_error():
    spec = {k: [o for o in v if o != "FeatureExtraction.use_gpu"] for k, v in NEW.items()}
    with pytest.raises(cc.ColmapCompatError) as e:
        _build(_caps(spec))
    msg = str(e.value)
    assert "feature_extractor" in msg and "FeatureExtraction.use_gpu" in msg and "4.2.1" in msg
    assert e.value.status == 501


def test_missing_optional_options_are_skipped_and_reported():
    spec = {k: [o for o in v if "num_threads" not in o and "max_num_features" not in o and "ba_use_gpu" not in o]
            for k, v in NEW.items()}
    cs = _build(_caps(spec))
    flat = " ".join(" ".join(a) for _, a in cs.commands)
    assert "num_threads" not in flat and "max_num_features" not in flat
    assert {s["option"] for s in cs.skipped} >= {"SiftExtraction.max_num_features", "Mapper.num_threads"}


def test_unreadable_help_is_an_error_not_a_guess():
    caps = cc.ColmapCaps("colmap", "4.2.1", {"feature_extractor": set()}, {"feature_extractor": "help output listed no options"})
    with pytest.raises(cc.ColmapCompatError) as e:
        _build(caps)
    assert "unusable" in str(e.value)


def test_oom_detection():
    assert cc.looks_like_oom(137, "") and cc.looks_like_oom(3221225477, "") and cc.looks_like_oom(1, "terminate: std::bad_alloc")
    assert not cc.looks_like_oom(1, "no features found")


def test_probe_runs_real_subprocess_and_reads_version(fake):
    exe, log = fake(NEW)
    caps = cc.probe(exe)
    assert caps.version == "4.2.1"
    assert "FeatureMatching.use_gpu" in caps.options["exhaustive_matcher"]
    assert not caps.help_errors


def test_probe_of_missing_binary_is_clear():
    with pytest.raises(cc.ColmapCompatError) as e:
        cc.probe("/definitely/not/colmap")
    assert "COLMAP_BIN" in str(e.value)


# ---- memory plan ---------------------------------------------------------------------------------------------------

def test_tiers_follow_free_ram():
    assert memory_plan.choose_tier(16000) == "normal"
    assert memory_plan.choose_tier(3200) == "low"
    assert memory_plan.choose_tier(1800) == "minimal"
    assert memory_plan.choose_tier(None) == "normal"


def test_three_gb_free_runs_in_low_mode_instead_of_refusing():
    p = memory_plan.make_plan(3000, 3)
    assert p.tier == "low" and p.threads <= 2 and p.max_side <= 720 and p.max_images <= 60


def test_too_little_ram_is_refused_with_advice():
    with pytest.raises(PipelineError) as e:
        memory_plan.make_plan(600, 3)
    assert "LOW_MEMORY_MODE=minimal" in str(e.value) and e.value.status == 503


def test_subsample_is_even_ordered_and_keeps_ends():
    frames = [{"name": f"f{i}", "t": i / 3} for i in range(100)]
    s = memory_plan.subsample(frames, 10)
    assert len(s) == 10 and s[0] is frames[0] and s[-1] is frames[-1]
    assert [f["t"] for f in s] == sorted(f["t"] for f in s)
    assert memory_plan.subsample(frames, 500) == frames


def test_step_down_chain_ends():
    assert memory_plan.step_down("normal") == "low" and memory_plan.step_down("low") == "minimal"
    assert memory_plan.step_down("minimal") is None


# ---- full _colmap_sfm path with the stand-in executable ---------------------------------------------------------------

def _frames(tmp_path, n=12):
    d = tmp_path / "frames"
    d.mkdir()
    frames = []
    for i in range(n):
        cv2.imwrite(str(d / f"f_{i:06d}.jpg"), np.full((60, 80, 3), 40 + i, np.uint8))
        frames.append({"name": f"f_{i:06d}.jpg", "file": f"frames/f_{i:06d}.jpg", "t": i / 3, "frame_index": i})
    return d, frames


def _run(tmp_path, exe, plan_free=16000):
    d, frames = _frames(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    caps = cc.get_caps(exe)
    plan = memory_plan.make_plan(plan_free, 3)
    ctx = jobs.JobContext(None)
    return reconstruct._colmap_with_retry(exe, d, frames, work, False, ctx, plan, caps), work


def test_sfm_path_runs_cpu_commands_and_cleans_up(fake, tmp_path):
    exe, log = fake(NEW)
    res, work = _run(tmp_path, exe)
    names = [c[0] for c in _calls(log) if len(c) > 1 and c[1] != "-h" and c[0] != "help"]
    assert names == ["feature_extractor", "exhaustive_matcher", "mapper", "model_converter"]
    fe = next(c for c in _calls(log) if c[0] == "feature_extractor" and "--database_path" in c)
    assert "--FeatureExtraction.use_gpu" in fe and "0" == fe[fe.index("--FeatureExtraction.use_gpu") + 1]
    assert len(res["poses"]) == 8 and len(res["points"]) > 0 and res["meta"]["colmap_version"] == "4.2.1"
    assert not (work / "images").exists()          # temporary copies removed
    assert json.loads((work / "report.json").read_text())["execution"]["memory_plan"]["tier"] == "normal"


def test_oom_retries_once_with_smaller_plan(fake, tmp_path):
    exe, log = fake(NEW, oom="once")
    res, work = _run(tmp_path, exe)
    assert res["meta"]["memory_plan"] == "low"
    assert len([c for c in _calls(log) if c[0] == "mapper" and "--output_path" in c]) == 2
    assert not (work / "images").exists()


def test_persistent_oom_fails_loudly_and_does_not_loop(fake, tmp_path):
    exe, log = fake(NEW, oom="always")
    with pytest.raises(PipelineError) as e:
        _run(tmp_path, exe)
    assert "memory" in str(e.value).lower()
    assert len([c for c in _calls(log) if c[0] == "mapper" and "--output_path" in c]) == 2     # normal + one retry, never more
    assert not (tmp_path / "work" / "images").exists()


def test_mapper_without_initial_pair_returns_capture_guidance(monkeypatch, tmp_path):
    class FailedProcess:
        returncode = 1

        def communicate(self, timeout):
            return "", "No good initial image pair found.\nFailed to create any sparse model"

    monkeypatch.setattr(reconstruct.colmap_locator, "env_for", lambda _: {})
    monkeypatch.setattr(reconstruct.subprocess, "Popen", lambda *args, **kwargs: FailedProcess())

    with pytest.raises(PipelineError, match="no camera pair had enough parallax") as error:
        reconstruct._run(["colmap", "mapper"], "mapper", jobs.JobContext(None), tmp_path)

    assert "genuine 360 panorama requires 2:1 equirectangular footage" in str(error.value)
    assert "No good initial image pair found" in (tmp_path / "mapper.stderr.log").read_text()


def test_too_few_registered_images_is_not_marked_success(fake, tmp_path):
    exe, _ = fake(NEW, registered=3)
    with pytest.raises(PipelineError) as e:
        _run(tmp_path, exe)
    assert e.value.status == 422 and "registered only 3" in str(e.value)


def test_unsupported_colmap_fails_before_running_anything(fake, tmp_path):
    spec = {k: [o for o in v if o != "FeatureMatching.use_gpu"] for k, v in NEW.items()}
    exe, log = fake(spec)
    with pytest.raises(cc.ColmapCompatError):
        _run(tmp_path, exe)
    ran = [c for c in _calls(log) if "--database_path" in c]
    assert [c[0] for c in ran] == []      # no stage executed with a guessed flag


def test_cancellation_stops_before_next_stage(fake, tmp_path):
    from app.errors import Cancelled
    exe, log = fake(NEW)
    d, frames = _frames(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    ctx = jobs.JobContext(None)
    ctx.cancel()
    with pytest.raises(Cancelled):
        reconstruct._colmap_with_retry(exe, d, frames, work, False, ctx, memory_plan.make_plan(16000, 3), cc.get_caps(exe))
    assert not [c for c in _calls(log) if "--database_path" in c]
