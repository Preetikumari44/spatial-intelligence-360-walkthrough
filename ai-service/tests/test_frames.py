import cv2
import numpy as np
import pytest

from app import config, video_pipeline
from app.errors import PipelineError


def _cand(blur, seed):
    rng = np.random.default_rng(seed)
    return {"blur": blur, "thumb": rng.integers(0, 255, (90, 160), dtype=np.uint8)}


def test_select_frames_drops_blur_and_duplicates():
    a = _cand(300, 1)
    dup = {"blur": 310, "thumb": a["thumb"].copy()}
    blurry = _cand(5, 2)
    b = _cand(280, 3)
    kept, drops = video_pipeline.select_frames([a, dup, blurry, b], blur_abs_min=25, dup_diff=2.5, max_frames=50)
    assert kept == [a, b]
    assert drops["dropped_blur"] == 1 and drops["dropped_duplicate"] == 1


def test_select_frames_caps_length_evenly():
    cands = [_cand(300, i) for i in range(100)]
    kept, drops = video_pipeline.select_frames(cands, max_frames=10)
    assert len(kept) == 10 and drops["dropped_cap"] == 90


def _write_video(path, frames=90, size=(640, 480), fps=30):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, (size[1] * 2, size[0] * 2, 3), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (0, 0), 1)
    for i in range(frames):
        x = int(i * 6)
        vw.write(np.ascontiguousarray(base[50:50 + size[1], x:x + size[0]]))
    vw.release()


def test_extract_frames_end_to_end_on_synthetic_video():
    rel = "videos/synthetic.mp4"
    path = config.resolve(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_video(path)
    summary = video_pipeline.extract_frames(rel, "jobs/t1/frames", is_360=False)
    assert summary["kept"] >= 8
    out = config.resolve("jobs/t1/frames")
    assert (out / "frames.json").exists()
    assert len(list(out.glob("f_*.jpg"))) == summary["kept"]


def test_unreadable_video_is_rejected():
    p = config.resolve("videos/bad.mp4")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"not a video")
    with pytest.raises(PipelineError):
        video_pipeline.probe("videos/bad.mp4")


def test_360_flag_requires_two_to_one_frames():
    rel = "videos/flat.mp4"
    path = config.resolve(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_video(path, frames=40)
    with pytest.raises(PipelineError):
        video_pipeline.probe(rel, is_360=True)
