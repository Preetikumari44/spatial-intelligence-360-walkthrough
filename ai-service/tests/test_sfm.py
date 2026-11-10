"""Camera pose estimation checked against a synthetic room whose true camera path is known."""
import numpy as np
import pytest

import synth
from app import colmap_locator, config, jobs, reconstruct, sfm
from app.errors import Cancelled, PipelineError


@pytest.fixture(scope="module")
def room():
    frames, depths, poses = synth.render_sequence(24)
    return frames, depths, poses


def test_opencv_sfm_recovers_camera_path(room, tmp_path):
    frames, _, poses = room
    meta = synth.write_frames(tmp_path / "frames", frames)
    res = sfm.run(tmp_path / "frames", meta, jobs.get(None))
    names = [m["name"] for m in meta]
    assert len(res["poses"]) >= 20, "most frames should register"
    est = np.array([res["poses"][n]["center"] for n in names if n in res["poses"]])
    truth = np.array([poses[i][0] for i, n in enumerate(names) if n in res["poses"]])
    s, R, t = synth.umeyama(est, truth)
    err = np.linalg.norm(s * est @ R.T + t - truth, axis=1)
    path_length = np.linalg.norm(np.diff(truth, axis=0), axis=1).sum()
    assert err.mean() < 0.03 * path_length          # under 3% of the path length
    assert abs(res["cams"][1]["fx"] - synth.F) / synth.F < 0.08   # focal self-calibration within 8%
    assert len(res["points"]) > 300
    assert res["meta"]["backend"] == "opencv-sfm"


def test_blank_footage_fails_instead_of_pretending(tmp_path):
    import cv2
    blank = [np.full((360, 480, 3), 128, np.uint8) for _ in range(10)]
    meta = synth.write_frames(tmp_path / "frames", blank)
    with pytest.raises(PipelineError):
        sfm.run(tmp_path / "frames", meta, jobs.get(None))


def test_reconstruct_writes_report_and_files(room, monkeypatch):
    frames, _, _ = room
    monkeypatch.setattr(colmap_locator, "locate", lambda: colmap_locator.Located(None, "none"))
    base = config.STORAGE_ROOT / "t_recon"
    synth.write_frames(base / "frames", frames)
    out = reconstruct.run("t_recon/frames", "t_recon/work", False)
    assert out["backend"] == "opencv-sfm" and out["registered_frames"] >= 20
    work = base / "work"
    assert (work / "reconstruction.json").exists() and (work / "points_full.npz").exists()
    import json
    rep = json.loads((work / "report.json").read_text())
    assert rep["stages"]["camera_poses"]["status"] == "ok"
    assert rep["execution"]["cuda_required"] is False


def test_360_without_colmap_is_refused_honestly(monkeypatch):
    monkeypatch.setattr(config, "COLMAP_BIN", "colmap-does-not-exist")
    monkeypatch.setattr(colmap_locator, "locate", lambda: colmap_locator.Located(None, "none"))
    with pytest.raises(PipelineError) as e:
        reconstruct.choose_backend(True)
    assert e.value.status == 503 and "COLMAP" in str(e.value)


def test_cancel_stops_reconstruction(room, tmp_path):
    frames, _, _ = room
    meta = synth.write_frames(tmp_path / "frames", frames)
    ctx = jobs.get("cancel-test", fresh=True)
    ctx.cancel()
    with pytest.raises(Cancelled):
        sfm.run(tmp_path / "frames", meta, ctx)


def test_low_memory_blocks_reconstruction(room, monkeypatch):
    frames, _, _ = room
    base = config.STORAGE_ROOT / "t_mem"
    synth.write_frames(base / "frames", frames)
    monkeypatch.setattr("app.hardware.available_ram_mb", lambda: 300)
    with pytest.raises(PipelineError) as e:
        reconstruct.run("t_mem/frames", "t_mem/work", False)
    assert e.value.status == 503 and "RAM" in str(e.value)


def test_chessboard_calibration_recovers_focal(tmp_path):
    import cv2
    square, cols, rows = 40, 9, 6
    board = np.full(((rows + 1) * square + 80, (cols + 1) * square + 80), 255, np.uint8)
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                board[40 + r * square:40 + (r + 1) * square, 40 + c * square:40 + (c + 1) * square] = 0
    K = np.array([[700.0, 0, 320], [0, 700.0, 240], [0, 0, 1]])
    rng = np.random.default_rng(3)
    paths = []
    for i in range(14):
        rvec = rng.uniform(-0.45, 0.45, 3)
        R = cv2.Rodrigues(rvec)[0]
        t = np.array([rng.uniform(-60, 60), rng.uniform(-40, 40), rng.uniform(500, 700)])
        # board pixel (x, y) maps to plane point (x, y, 0) in the same units as t
        H = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ np.array([[1, 0, -board.shape[1] / 2], [0, 1, -board.shape[0] / 2], [0, 0, 1]])
        img = cv2.warpPerspective(board, H, (640, 480), borderValue=255)
        p = tmp_path / f"b{i}.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
    res = sfm.calibrate_chessboard(paths, (cols, rows), 40.0)
    assert abs(res["fx"] - 700) / 700 < 0.05
    assert res["rms_reprojection_px"] < 1.0
