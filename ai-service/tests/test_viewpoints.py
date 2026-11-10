"""Pipeline A (frames -> viewpoints -> navigation graph -> hotspots -> validation), which must work without COLMAP or any 3D library."""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

import synth
from app import config, video_pipeline, viewpoints
from app.errors import PipelineError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_test_video.py"


def _frames(tmp_path, tag, kind="room", is_360=False):
    out = tmp_path / f"{tag}.mp4"
    subprocess.run([sys.executable, str(SCRIPT), str(out), "--kind", kind, "--frames", "120", "--width", "640"], check=True, capture_output=True)
    rel = f"videos/{tag}.mp4"
    dst = config.resolve(rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out.read_bytes())
    video_pipeline.extract_frames(rel, f"jobs/{tag}/frames", is_360)
    return f"jobs/{tag}/frames"


def test_tour_is_built_from_real_frames_without_colmap_or_poses(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SFM_BACKEND", "colmap")          # COLMAP "required" and absent: Pipeline A must not care
    monkeypatch.setattr(config, "COLMAP_BIN", str(tmp_path / "does-not-exist.exe"))
    fr = _frames(tmp_path, "pa1")
    t = viewpoints.build(fr, "jobs/pa1/tour", False)
    nodes, conns = t["nodes"], t["connections"]
    assert len(nodes) >= 5 and t["validation"]["passed"]
    extracted = json.loads((config.resolve(fr) / "frames.json").read_text())["frames"]
    assert len(nodes) == len(extracted)
    assert all(n["position"] is None and n["has_pose"] is False for n in nodes)            # no poses are claimed
    assert [n["label"] for n in nodes] == [f"Viewpoint {i + 1:02d}" for i in range(len(nodes))]   # neutral labels, no invented room types
    assert all(config.resolve(n["frame"]).is_file() and config.resolve(n["thumb"]).is_file() for n in nodes)
    times = [n["time_sec"] for n in nodes]
    assert times == sorted(times) and all(n["video_frame_index"] >= 0 for n in nodes)       # timestamps of the original footage kept
    frames_json = {f["name"]: f for f in json.loads((config.resolve(fr) / "frames.json").read_text())["frames"]}
    assert all(frames_json[n["frame_id"]]["t"] == n["time_sec"] for n in nodes)             # node == the real extracted frame
    m = json.loads((config.resolve("jobs/pa1/tour") / "tour_manifest.json").read_text())
    assert m["mode"] == "viewpoint" and m["has_poses"] is False and m["floorplan"]["kind"] == "none"
    assert any("360" in w for w in m["warnings"])                                           # flat video is not presented as 360


def test_all_extracted_frames_are_kept_without_a_viewpoint_cap(monkeypatch):
    count = 75
    frames = [{"t": i / 3} for i in range(count)]
    descs = [{"hist": np.array([i / count], dtype=np.float32)} for i in range(count)]
    monkeypatch.setattr(viewpoints, "_relate", lambda *args, **kwargs: {"inliers": config.TOUR_VERIFY_INLIERS})

    idx, segments, rels = viewpoints._connect_all_frames(frames, descs, False)

    assert idx == list(range(count))
    assert len(rels) > count - 1
    assert all((i, i + 1) in rels for i in range(count - 1))
    assert segments == [0] * count


def test_nonconsecutive_appearance_candidates_are_geometrically_checked(monkeypatch):
    frames = [{"t": float(i)} for i in range(16)]
    descs = [{"hist": np.array([i], dtype=np.float32), "index": i} for i in range(len(frames))]
    checked = []

    def distance(a, b):
        pair = tuple(sorted((int(a[0]), int(b[0]))))
        return 0.0 if pair == (0, 12) else float(abs(a[0] - b[0]))

    def relate(a, b, geometric=True):
        checked.append((a["index"], b["index"]))
        return {"inliers": 0}

    monkeypatch.setattr(viewpoints, "_hdist", distance)
    monkeypatch.setattr(viewpoints, "_relate", relate)
    viewpoints._connect_all_frames(frames, descs, False)

    assert (0, 12) in checked


def test_large_viewpoint_collection_has_bounded_expensive_match_count(monkeypatch):
    count = 400
    frames = [{"t": float(i)} for i in range(count)]
    descs = [{"hist": np.array([i / count], dtype=np.float32)} for i in range(count)]
    checked = []
    monkeypatch.setattr(viewpoints, "_relate", lambda a, b, **kwargs: checked.append((a, b)) or {"inliers": 0})

    viewpoints._connect_all_frames(frames, descs, False)

    assert len(checked) < count * 20
    assert len({tuple(sorted((a["hist"][0], b["hist"][0]))) for a, b in checked}) == len(checked)


def test_2d_feature_overlap_never_invents_an_image_hotspot():
    rel = {"inliers": 80, "scale": 1.1, "centroid": [0.7, 0.5], "tx": -0.1}

    hotspot = viewpoints._hotspot_flow(rel, False)

    assert hotspot["visible"] is False
    assert hotspot["directional"] is False


def test_sequence_links_cover_the_whole_video_and_hotspots_are_sane(tmp_path):
    t = viewpoints.build(_frames(tmp_path, "pa2"), "jobs/pa2/tour", False)
    n = len(t["nodes"])
    seq = {(c["from"], c["to"]) for c in t["connections"] if c["kind"] == "sequence"}
    assert all((f"n{i}", f"n{i + 1}") in seq and (f"n{i + 1}", f"n{i}") in seq for i in range(n - 1))
    for c in t["connections"]:
        h = c["hotspot"]
        assert np.isfinite(h["bearing"])
        assert h["visible"] is False
    behind = [c for c in t["connections"] if c["kind"] == "sequence" and int(c["to"][1:]) < int(c["from"][1:])]
    assert all(not c["hotspot"]["visible"] for c in behind)
    assert sum(1 for c in t["connections"] if c["kind"] == "revisit") <= 2 * n               # no web of random links


def test_360_footage_gets_panorama_nodes_but_no_invented_directions(tmp_path):
    rng = np.random.default_rng(5)                                     # 2:1 equirectangular-shaped footage (a slow sideways pan)
    scene = cv2.GaussianBlur(cv2.resize(rng.integers(0, 255, (180, 900, 3), dtype=np.uint8), (3600, 720), interpolation=cv2.INTER_NEAREST), (0, 0), 2.0)
    out = tmp_path / "pano.mp4"
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 15, (1280, 640))
    for i in range(90):
        vw.write(cv2.resize(scene[40:680, i * 12:i * 12 + 1280], (1280, 640)))
    vw.release()
    config.resolve("videos/pa3.mp4").parent.mkdir(parents=True, exist_ok=True)
    config.resolve("videos/pa3.mp4").write_bytes(out.read_bytes())
    video_pipeline.extract_frames("videos/pa3.mp4", "jobs/pa3/frames", True)
    t = viewpoints.build("jobs/pa3/frames", "jobs/pa3/tour", True)
    assert all(n["panorama"] is True for n in t["nodes"])
    assert all(c["hotspot"]["visible"] is False and c["hotspot"]["directional"] is False for c in t["connections"])
    manifest = json.loads((config.resolve("jobs/pa3/tour") / "tour_manifest.json").read_text())
    assert manifest["panorama_coverage"]["status"] == "source_declared_not_content_verified"
    assert manifest["panorama_coverage"]["asset_method"] == "original_extracted_video_frame"
    assert "not stitched panoramas" in manifest["panorama_coverage"]["note"]


def test_360_tour_rejects_non_equirectangular_extracted_frames(tmp_path):
    frames_dir = config.resolve("jobs/nonpano/frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame = frames_dir / "frame.jpg"
    cv2.imwrite(str(frame), np.zeros((240, 320, 3), dtype=np.uint8))
    (frames_dir / "frames.json").write_text(json.dumps({
        "summary": {"duration_sec": 1.0},
        "frames": [{"file": f"jobs/nonpano/frames/frame.jpg", "name": "frame.jpg", "t": 0.0, "frame_index": 0},
                   {"file": f"jobs/nonpano/frames/frame.jpg", "name": "frame.jpg", "t": 0.5, "frame_index": 1}],
    }))

    with pytest.raises(PipelineError, match="must remain 2:1 equirectangular"):
        viewpoints.build("jobs/nonpano/frames", "jobs/nonpano/tour", True)


def _cut_video(tmp_path, tag):
    rng = np.random.default_rng(11)
    out = tmp_path / f"{tag}.mp4"
    W, H = 480, 360
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 15, (W, H))
    path = synth.camera_path(60)
    for c, R in path[:60]:
        vw.write(synth.render(c, R, W, H, 0.875 * W)[0])
    tex = cv2.GaussianBlur(cv2.resize(rng.integers(0, 255, (90, 360, 3), dtype=np.uint8), (W * 3, H * 2), interpolation=cv2.INTER_NEAREST), (0, 0), 1.2)
    for i in range(60):                                                # a completely different "room": slowly panning over another texture
        x = i * 4
        vw.write(tex[20:20 + H, x:x + W].copy())
    vw.release()
    rel = f"videos/{tag}.mp4"
    config.resolve(rel).parent.mkdir(parents=True, exist_ok=True)
    config.resolve(rel).write_bytes(out.read_bytes())
    video_pipeline.extract_frames(rel, f"jobs/{tag}/frames", False)
    return f"jobs/{tag}/frames", 60 / 15.0


def test_a_scene_cut_is_not_bridged_by_a_made_up_link(tmp_path):
    """Unrelated clips remain visible as separate viewpoints and are never joined by an unverified link."""
    fr, cut_t = _cut_video(tmp_path, "pa4")
    t = viewpoints.build(fr, "jobs/pa4/tour", False)
    assert all(c["verified"] for c in t["connections"])                              # no unverified link exists at all
    sides = {n["time_sec"] >= cut_t - 0.01 for n in t["nodes"]}
    assert sides == {True, False}
    extracted = json.loads((config.resolve(fr) / "frames.json").read_text())["frames"]
    assert len(t["nodes"]) == len(extracted)
    m = json.loads((config.resolve("jobs/pa4/tour") / "tour_manifest.json").read_text())
    assert m["coverage"]["segments_found"] >= 2 and m["coverage"]["viewpoints_left_out"] == 0
    assert any("separate viewpoint groups" in w for w in m["warnings"])
    assert t["validation"]["passed"]


def test_legacy_switch_restores_video_order_links_and_flags_them(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TOUR_ALLOW_UNVERIFIED_LINKS", True)
    fr, cut_t = _cut_video(tmp_path, "pa4b")
    t = viewpoints.build(fr, "jobs/pa4b/tour", False)
    assert any(not c["verified"] for c in t["connections"])                          # the old behaviour, now an explicit opt-in
    assert {n["time_sec"] >= cut_t - 0.01 for n in t["nodes"]} == {True, False}


def test_damaged_frame_output_is_refused_not_papered_over(tmp_path):
    fr = _frames(tmp_path, "pa5")
    first = json.loads((config.resolve(fr) / "frames.json").read_text())["frames"][0]
    config.resolve(first["file"]).unlink()
    with pytest.raises(PipelineError, match="cannot be read"):
        viewpoints.build(fr, "jobs/pa5/tour", False)


def test_validation_rejects_broken_graphs():
    n = [{"id": "n0", "frame": "nope/a.jpg", "thumb": "nope/a.jpg", "frame_id": "a.jpg", "time_sec": 2.0},
         {"id": "n1", "frame": "nope/b.jpg", "thumb": "nope/b.jpg", "frame_id": "b.jpg", "time_sec": 1.0}]
    c = [{"from": "n0", "to": "n9", "hotspot": {"visible": True, "x": 1.5, "y": 0.5}}]
    v = viewpoints._validate(None, n, c, {})
    failed = {x["check"] for x in v["checks"] if not x["ok"]}
    assert not v["passed"] and {"viewpoint images exist", "timestamps are in capture order", "every extracted frame is a viewpoint",
                                "hotspot coordinates inside the image"} <= failed


def test_dark_and_overexposed_frames_are_flagged(tmp_path):
    d = config.resolve("jobs/exp/frames")
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    for name, img in (("dark.jpg", np.full((240, 320, 3), 12, np.uint8)), ("bright.jpg", np.full((240, 320, 3), 252, np.uint8)),
                      ("ok.jpg", rng.integers(60, 200, (240, 320, 3), dtype=np.uint8))):
        cv2.imwrite(str(d / name), img)
    fr = [{"file": f"jobs/exp/frames/{n}", "name": n, "t": i, "frame_index": i} for i, n in enumerate(("dark.jpg", "bright.jpg", "ok.jpg"))]
    ex = [x["exposure"]["flag"] for x in viewpoints._describe(fr)]
    assert ex == ["dark", "overexposed", None]


def test_pipeline_a_does_not_import_the_3d_stack():
    code = "import sys; sys.path.insert(0,'.'); import app.viewpoints; bad=[m for m in ('app.colmap_compat','app.reconstruct','app.dense','app.splat','open3d','torch') if m in sys.modules]; print(bad)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
