"""Motion-adaptive frame sampling: static / blurry / corrupt rejection, overlap, ordering, timestamps, room transitions."""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from app import config, video_pipeline
from app.errors import PipelineError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_test_video.py"


def _make(tmp_path, kind, frames=120, width=640):
    out = tmp_path / f"{kind}.mp4"
    subprocess.run([sys.executable, str(SCRIPT), str(out), "--kind", kind, "--frames", str(frames), "--width", str(width)],
                   check=True, capture_output=True)
    rel = f"videos/{kind}_{abs(hash(str(tmp_path))) % 10**6}.mp4"
    dst = config.resolve(rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out.read_bytes())
    return rel


def _frames_json(rel_out):
    import json
    return json.loads((config.resolve(rel_out) / "frames.json").read_text())


def test_room_walk_keeps_overlapping_ordered_frames(tmp_path):
    rel = _make(tmp_path, "room")
    s = video_pipeline.extract_frames(rel, "jobs/ad_room/frames", False)
    d = _frames_json("jobs/ad_room/frames")
    ts = [f["t"] for f in d["frames"]]
    idx = [f["frame_index"] for f in d["frames"]]
    assert s["sampling"] == "adaptive" and s["kept"] >= config.MIN_FRAMES
    assert ts == sorted(ts) and len(set(ts)) == len(ts)          # strictly ordered, timestamps preserved
    assert idx == sorted(idx) and all(f["motion_since_previous"] >= 0 for f in d["frames"][1:])
    assert s["dropped_blur"] >= 1                                  # the injected motion-blur burst is detected
    assert s["source_frames"] == 120 and s["settings"]["effective_fps"] and s["resolution"]["extracted"] == [640, 480]
    assert s["extraction_seconds"] >= 0 and (config.resolve("jobs/ad_room/frames") / "preview.jpg").is_file()
    # consecutive kept frames must still look alike (overlap): mean grey difference stays moderate
    out = config.resolve("jobs/ad_room/frames")
    grays = [cv2.resize(cv2.imread(str(out / f["name"]), 0), (160, 120)) for f in d["frames"]]
    diffs = [float(np.mean(cv2.absdiff(a, b))) for a, b in zip(grays, grays[1:])]
    assert max(diffs) < 60, diffs


def test_stationary_hold_is_not_kept_as_many_frames(tmp_path):
    rel = _make(tmp_path, "room")
    s = video_pipeline.extract_frames(rel, "jobs/ad_room2/frames", False)
    d = _frames_json("jobs/ad_room2/frames")
    first_second = [f for f in d["frames"] if f["t"] < 0.6]       # the first 10 frames (0.67 s) are an identical hold
    assert len(first_second) <= 1


def test_static_camera_is_rejected_with_advice(tmp_path):
    rel = _make(tmp_path, "static")
    with pytest.raises(PipelineError, match="hardly moves"):
        video_pipeline.extract_frames(rel, "jobs/ad_static/frames", False)


def test_blurry_footage_is_rejected(tmp_path):
    rel = _make(tmp_path, "blurry")
    with pytest.raises(PipelineError, match="usable frames"):
        video_pipeline.extract_frames(rel, "jobs/ad_blur/frames", False)


def test_corrupt_video_is_rejected():
    p = config.resolve("videos/corrupt_ad.mp4")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"junk" * 50)
    with pytest.raises(PipelineError):
        video_pipeline.extract_frames("videos/corrupt_ad.mp4", "jobs/ad_corrupt/frames", False)


def test_avi_video_is_probed_when_opencv_decoder_supports_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_ROOT", tmp_path)
    path = tmp_path / "videos" / "walkthrough.avi"
    path.parent.mkdir(parents=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (640, 480))
    if not writer.isOpened():
        pytest.skip("OpenCV has no MJPEG AVI encoder available")
    for i in range(20):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(frame, (20 + i * 5, 80), (220 + i * 5, 360), (40, 180, 230), -1)
        writer.write(frame)
    writer.release()

    info = video_pipeline.probe("videos/walkthrough.avi")

    assert info["width"] == 640
    assert info["height"] == 480
    assert info["frame_count"] == 20
    assert info["duration_sec"] == 2.0


def _probe(t, tex, dx, blur=300.0):
    h, w = tex.shape
    thumb = cv2.resize(np.ascontiguousarray(tex[10:10 + 90 * 3, dx:dx + 160 * 3]), (160, 90), interpolation=cv2.INTER_AREA)
    return {"t": t, "blur": blur, "thumb": thumb, "frame_index": int(t * 30)}


def test_scene_cut_keeps_frames_on_both_sides():
    rng = np.random.default_rng(3)
    blocky = lambda: cv2.resize(rng.integers(0, 255, (40, 160), dtype=np.uint8), (1600, 400), interpolation=cv2.INTER_NEAREST)  # noqa: E731
    a = blocky()
    b = 255 - blocky()          # a different room: contrast survives down-sampling
    probes = [_probe(i * 0.125, a, i * 3) for i in range(16)] + [_probe(2.0 + i * 0.125, b, i * 3) for i in range(16)]
    chosen, st = video_pipeline.plan_adaptive(probes)
    assert st["transitions"] == 1
    before = [c for c in chosen if c["t"] < 2.0]
    after = [c for c in chosen if c["t"] >= 2.0]
    assert before and after
    assert after[0].get("transition") is True and after[0]["t"] == 2.0   # first frame of the new room is kept and marked


def test_uneven_timestamps_are_preserved_in_order():
    rng = np.random.default_rng(4)
    a = cv2.GaussianBlur(rng.integers(0, 255, (400, 1600), dtype=np.uint8), (0, 0), 1.5)
    ts = [0.0, 0.1, 0.35, 0.4, 0.9, 1.0, 1.7, 1.75, 2.4, 2.5, 3.3, 3.4]   # variable frame rate: gaps differ
    probes = [_probe(t, a, int(t * 100)) for t in ts]
    chosen, _ = video_pipeline.plan_adaptive(probes)
    got = [c["t"] for c in chosen]
    assert got == sorted(got) and set(got) <= set(ts)


def test_fixed_mode_still_available(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FRAME_SAMPLING", "fixed")
    rel = _make(tmp_path, "pan")
    s = video_pipeline.extract_frames(rel, "jobs/ad_fixed/frames", False)
    assert s["sampling"] == "fixed" and s["kept"] >= config.MIN_FRAMES
