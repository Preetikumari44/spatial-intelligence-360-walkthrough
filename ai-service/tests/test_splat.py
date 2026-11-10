"""Gaussian splat file formats and a short real training run."""
import json

import numpy as np
import pytest

import synth
from app import config, dense, jobs, reconstruct, splat

torch = pytest.importorskip("torch")


def test_cpu_gaussian_trainer_smoke():
    assert splat.cpu_smoke_test()


def _gaussians(n=500, seed=0):
    rng = np.random.default_rng(seed)
    q = rng.normal(size=(n, 4))
    return splat.Gaussians(rng.uniform(-3, 3, (n, 3)), rng.uniform(-5, -2, (n, 3)), q, rng.normal(0, 2, n), rng.uniform(0.05, 0.95, (n, 3)))


def test_gaussian_ply_round_trip(tmp_path):
    g = _gaussians()
    splat.write_gaussian_ply(tmp_path / "a.ply", g)
    h = splat.read_gaussian_ply(tmp_path / "a.ply")
    assert np.allclose(g.xyz, h.xyz) and np.allclose(g.rgb, h.rgb, atol=1e-5) and np.allclose(g.log_scale, h.log_scale)
    raw = (tmp_path / "a.ply").read_bytes()
    head = raw[:raw.index(b"end_header")].decode("ascii")
    assert "property float f_dc_0" in head and "property float rot_3" in head and "property float opacity" in head


def test_splat_round_trip_is_quantised_but_close(tmp_path):
    g = _gaussians()
    splat.write_splat(tmp_path / "a.splat", g)
    assert (tmp_path / "a.splat").stat().st_size == 32 * len(g)
    h = splat.read_splat(tmp_path / "a.splat")
    assert len(h) == len(g)
    order = np.lexsort((g.xyz[:, 0],))          # the writer sorts, so compare as sets of positions
    assert np.allclose(np.sort(g.xyz[:, 0]), np.sort(h.xyz[:, 0]), atol=1e-5)
    assert np.abs(h.rgb.mean() - g.rgb.mean()) < 0.02


def test_spz_round_trip(tmp_path):
    g = _gaussians()
    splat.write_spz(tmp_path / "a.spz", g)
    h = splat.read_spz(tmp_path / "a.spz")
    assert len(h) == len(g)
    assert np.allclose(g.xyz, h.xyz, atol=1.0 / (1 << 11))
    assert np.abs(h.rgb - g.rgb).mean() < 0.02


def test_training_improves_psnr_on_synthetic_room():
    frames, _, _ = synth.render_sequence(16)
    base = config.STORAGE_ROOT / "t_splat"
    synth.write_frames(base / "frames", frames)
    reconstruct.run("t_splat/frames", "t_splat/work", False)
    dense.build_pointcloud("t_splat/work", jobs.get(None))
    old = (config.SPLAT_ITERATIONS, config.SPLAT_MAX_GAUSSIANS)
    config.SPLAT_ITERATIONS, config.SPLAT_MAX_GAUSSIANS = 25, 800
    try:
        out = splat.run_stage("t_splat/work", "t_splat/frames", jobs.get(None))
    finally:
        config.SPLAT_ITERATIONS, config.SPLAT_MAX_GAUSSIANS = old
    assert out["status"] == "ok"
    rep = json.loads((base / "work" / "report.json").read_text())
    st = rep["stages"]["gaussian_splat"]["stats"]
    assert st["iterations_run"] == 25
    assert st["psnr_train_after"] > st["psnr_train_before"] + 1.0     # the model really learned something
    keys = {o["key"] for o in rep["outputs"]}
    assert {"gaussian_ply", "gaussian_splat", "gaussian_spz", "splat_preview"} <= keys
    for o in rep["outputs"]:
        assert (config.STORAGE_ROOT / o["path"]).stat().st_size == o["size_bytes"] > 0
    # the Open3D renderer needs Vulkan; whatever happened must be reported truthfully, not hidden
    assert "open3d" in rep["stages"]["gaussian_splat"]["rendering"]


def test_splat_stage_unavailable_without_torch(monkeypatch):
    def boom():
        from app.errors import PipelineError
        raise PipelineError("PyTorch is not installed", 503)
    monkeypatch.setattr(splat, "_torch", boom)
    out = splat.run_stage("t_splat/work", "t_splat/frames", jobs.get(None))
    assert out["status"] == "unavailable"
