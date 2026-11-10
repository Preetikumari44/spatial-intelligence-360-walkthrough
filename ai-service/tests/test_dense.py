"""Point cloud, TSDF mesh and ICP. The depth provider below is TEST-ONLY: it returns the synthetic scene's true depth,
scrambled by an unknown scale and shift the way a monocular network's output would be."""
import json

import numpy as np
import pytest

import synth
from app import config, dense, jobs, reconstruct

o3d = pytest.importorskip("open3d")


class TruthDepth:
    name = "synthetic-truth (test only)"

    def __init__(self, names, poses):
        self.names, self.poses = names, poses

    def depth(self, bgr, name):
        c, R = self.poses[self.names.index(name)]
        _, d = synth.render(c, R, bgr.shape[1], bgr.shape[0], synth.F * bgr.shape[1] / synth.W)
        return 0.7 * d + 0.3


@pytest.fixture(scope="module")
def built():
    frames, _, poses = synth.render_sequence(24)
    base = config.STORAGE_ROOT / "t_dense"
    meta = synth.write_frames(base / "frames", frames)
    reconstruct.run("t_dense/frames", "t_dense/work", False)
    return meta, poses


def test_point_cloud_ply_is_real(built):
    out = dense.build_pointcloud("t_dense/work", jobs.get(None))
    assert out["status"] == "ok"
    pcd = o3d.io.read_point_cloud(str(config.resolve("t_dense/work/outputs/pointcloud.ply")))
    assert len(pcd.points) > 300 and pcd.has_colors() and pcd.has_normals()


def test_mesh_matches_true_room_geometry(built):
    meta, poses = built
    names = [m["name"] for m in meta]
    out = dense.build_mesh("t_dense/work", "t_dense/frames", jobs.get(None), provider=TruthDepth(names, poses))
    assert out["status"] == "ok" and out["triangles"] > 1000
    mesh = o3d.io.read_triangle_mesh(str(config.resolve("t_dense/work/outputs/mesh.ply")))
    assert len(mesh.triangles) == out["triangles"]
    # map the mesh into the true frame using camera positions AND orientations, then compare with the room's planes
    rec = json.loads(config.resolve("t_dense/work/reconstruction.json").read_text())
    est = np.array([rec["images"][n]["center"] for n in names])
    gt = np.array([c for c, _ in poses])
    M = sum(poses[i][1].T @ np.array(rec["images"][n]["axes"]) for i, n in enumerate(names))
    U, _, Vt = np.linalg.svd(M)
    Rr = U @ Vt
    er = est @ Rr.T
    s = np.linalg.norm(gt - gt.mean(0)) / np.linalg.norm(er - er.mean(0))
    t = gt.mean(0) - s * er.mean(0)
    v = s * np.asarray(mesh.vertices) @ Rr.T + t
    r = synth.ROOM
    dist = np.minimum.reduce([np.abs(v[:, 0] - r["x"][0]), np.abs(v[:, 0] - r["x"][1]), np.abs(v[:, 1] - r["y"][0]),
                              np.abs(v[:, 1] - r["y"][1]), np.abs(v[:, 2] - r["z"][1]), np.abs(v[:, 2] - r["z"][0])])
    assert np.median(dist) < 0.05          # metres, in a 6 x 3 x 8 m room
    rep = json.loads(config.resolve("t_dense/work/report.json").read_text())
    assert rep["stages"]["mesh"]["status"] == "ok"
    assert {"mesh_ply", "mesh_obj"} <= {o["key"] for o in rep["outputs"]}


def test_mesh_reports_unavailable_without_depth_source(built, monkeypatch):
    monkeypatch.setattr(dense, "default_provider", lambda: (None, "no model in this test"))
    out = dense.build_mesh("t_dense/work", "t_dense/frames", jobs.get(None))
    assert out["status"] == "unavailable"
    rep = json.loads(config.resolve("t_dense/work/report.json").read_text())
    assert rep["stages"]["mesh"]["status"] == "unavailable" and "no model" in rep["stages"]["mesh"]["message"]


def test_depth_alignment_recovers_scale_and_shift():
    rng = np.random.default_rng(1)
    raw = rng.uniform(1, 5, 300)
    z = 2.5 * raw + 0.4 + rng.normal(0, 0.01, 300)
    z[:40] += rng.uniform(1, 3, 40)                      # outliers
    s, b, ratio = dense.align_depth(raw, None, z)
    assert abs(s - 2.5) < 0.05 and abs(b - 0.4) < 0.1 and ratio > 0.7


def test_icp_recovers_a_known_transform():
    rng = np.random.default_rng(0)
    pts = rng.uniform(-1, 1, (3000, 3)).astype(np.float32)
    ang = np.radians(4)
    R = np.array([[np.cos(ang), -np.sin(ang), 0], [np.sin(ang), np.cos(ang), 0], [0, 0, 1]], np.float32)
    moved = pts @ R.T + np.array([0.03, -0.02, 0.01], np.float32)
    T, fitness, rmse = dense.icp_refine(pts, moved, 0.3)
    assert fitness > 0.9 and rmse < 0.01
    assert np.allclose(T[:3, :3], R, atol=0.01)


def test_cpu_tsdf_smoke_integrates_a_mesh():
    assert dense.cpu_smoke_test()
