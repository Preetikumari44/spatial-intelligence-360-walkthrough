"""Viewpoint links must be proven by shared 3D landmarks, never by video order or by distance alone."""
import json

import numpy as np
import pytest

from app import config, tour, viewgraph

CAM = {"w": 640, "h": 480, "fx": 500.0, "fy": 500.0, "cx": 320.0, "cy": 240.0}


def _node(x, lm, t):
    return {"center": np.array([x, 0.0, 0.0]), "axes": np.eye(3), "camera": CAM, "landmarks": set(lm), "t": float(t)}


def _points(n=400, blocks=()):
    """Landmark k sits at x = 0.025 k: a camera at x = 0.5 i sees landmarks 20 i .. 20 i + 60 (consistent with _node / _chain below).
    blocks = [(first_id, x0)]: landmarks from first_id on sit at x0 + 0.025 (k - first_id), for a second room filmed from other positions."""
    rng = np.random.default_rng(3)
    x = np.arange(n) * 0.025
    for first, x0 in blocks:
        x[first:] = x0 + (np.arange(first, n) - first) * 0.025
    return np.column_stack([x, rng.uniform(-1, 1, n), rng.uniform(4, 6, n)])


def _chain(n, per=60, step=20):
    """n viewpoints along a line; neighbours share 40 landmarks, distant ones none."""
    return [_node(i * 0.5, range(i * step, i * step + per), t=i) for i in range(n)]


def test_neighbours_that_share_landmarks_are_linked_and_the_chain_is_connected():
    nodes = _chain(8)
    g = viewgraph.build(nodes, _points(1000))
    pairs = {(m["i"], m["j"]) for m in g["edges"]}
    assert all((i, i + 1) in pairs for i in range(7))
    assert g["main"] == list(range(8)) and len(g["components"]) == 1
    assert all(m["shared"] >= g["min_shared"] for m in g["edges"])


def test_consecutive_frames_without_shared_landmarks_are_not_linked():
    """The old graph always linked viewpoint i to i+1. Here the camera 'cuts' to another room between viewpoint 3 and 4."""
    a = [_node(i * 0.5, range(i * 20, i * 20 + 60), i) for i in range(4)]
    b = [_node(2.0 + i * 0.5, range(500 + i * 20, 500 + i * 20 + 60), 4 + i) for i in range(4)]
    g = viewgraph.build(a + b, _points(1000, blocks=[(500, 2.0)]))
    pairs = {(m["i"], m["j"]) for m in g["edges"]}
    assert (3, 4) not in pairs
    assert not any(i < 4 <= j for i, j in pairs)
    assert len(g["components"]) == 2


def test_nearby_viewpoints_on_opposite_sides_of_a_wall_are_not_linked():
    near_a = _node(0.0, range(0, 60), 0)
    near_b = _node(0.1, range(300, 360), 10)                    # 10 cm away, but sees completely different landmarks
    g = viewgraph.build([near_a, near_b], _points(1000))
    assert g["edges"] == []


def test_loop_closure_is_labelled_and_needs_stronger_evidence():
    nodes = _chain(10)
    nodes[9]["landmarks"] = set(range(0, 60))                   # the camera returns to where it started: 60 common landmarks
    nodes[9]["center"] = np.array([0.2, 0.0, 0.0])
    g = viewgraph.build(nodes, _points(1000))
    loops = [m for m in g["edges"] if m["kind"] == "loop_closure"]
    assert (0, 9) in [(m["i"], m["j"]) for m in loops]           # the revisit is found, and it is labelled as a loop, not a neighbour
    assert all(m["j"] - m["i"] > 5 for m in loops)
    weak = _chain(10)
    weak[0]["landmarks"] |= set(range(80, 92))                  # a window both ends of the walk can see: only 12 common landmarks
    weak[9]["landmarks"] |= set(range(80, 92))
    g2 = viewgraph.build(weak, _points(1000))
    assert not [m for m in g2["edges"] if m["kind"] == "loop_closure"]


def test_a_weak_loop_is_kept_when_it_is_the_only_bridge():
    a = [_node(i * 0.5, range(i * 20, i * 20 + 60), i) for i in range(6)]
    b = [_node(2.7 + i * 0.5, range(700 + i * 20, 700 + i * 20 + 60), 20 + i) for i in range(6)]
    b[0]["landmarks"] |= set(range(100, 112))                   # 12 landmarks shared with a[5]: weak, but real
    a[5]["landmarks"] |= set(range(100, 112))
    g = viewgraph.build(a + b, _points(1000, blocks=[(700, 2.7)]))
    assert len(g["components"]) == 1                            # the only evidence that joins the two halves is used, not discarded


def test_parallax_is_required_pure_rotation_is_not_a_viewpoint_change():
    p = _points(400)
    a, b = _node(0.0, range(60), 0), _node(0.0, range(60), 5)    # same position, same landmarks
    g = viewgraph.build([a, b], p)
    assert g["edges"] == []


def test_landmarks_behind_the_camera_do_not_count_as_shared():
    p = _points(400)
    p[:60, 2] = -5.0                                            # the first 60 landmarks lie behind both cameras
    g = viewgraph.build([_node(0.0, range(60), 0), _node(0.5, range(60), 3)], p)
    assert g["edges"] == []


def _recon_dir(tmp_path, monkeypatch, xs, obs):
    work = tmp_path / "recon"
    work.mkdir()
    n = len(xs)
    frames = [{"stem": f"f{i}", "name": f"f{i}.jpg", "file": f"frames/f{i}.jpg", "t": float(i), "frame_index": i, "registered": True} for i in range(n)]
    images = {f"f{i}.jpg": {"center": [float(xs[i]), 0.0, 0.0], "axes": np.eye(3).tolist(), "camera_id": 1} for i in range(n)}
    recon = {"is_360": False, "frames": frames, "images": images, "cameras": {"1": CAM}, "extents": {"x": 9.0, "y": 1.0, "z": 1.0},
             "registered_images": n, "total_images": n}
    (work / "reconstruction.json").write_text(json.dumps(recon))
    (work / "points_preview.json").write_text(json.dumps({"positions": []}))
    np.savez_compressed(work / "points_full.npz", positions=_points(1000).astype(np.float32))
    (work / "observations.json").write_text(json.dumps({"version": 1, "landmarks": 1000, "images": {f"f{i}.jpg": list(obs[i]) for i in range(n)}}))
    monkeypatch.setattr(config, "resolve", lambda _: work)
    return work


def test_tour_retains_each_disconnected_component_without_inventing_a_link(tmp_path, monkeypatch):
    xs = [i * 0.5 for i in range(8)] + [15.0 + (i - 8) * 0.5 for i in range(8, 14)]
    obs = [range(i * 20, i * 20 + 60) for i in range(8)] + [range(600 + (i - 8) * 20, 660 + (i - 8) * 20) for i in range(8, 14)]
    work = _recon_dir(tmp_path, monkeypatch, xs, obs)
    t = tour.build("jobs/x/recon", False)
    assert len(t["nodes"]) == len(xs)
    m = json.loads((work / "tour_manifest.json").read_text())
    assert m["graph"]["components_found"] == 2
    assert m["graph"]["viewpoints_left_out"] == 0
    assert len(m["graph"]["components"]) == 2
    assert m["graph"]["unconnected_viewpoints"]
    assert any("graph components were found" in w for w in m["warnings"])
    assert all(c["verified"] and c["hotspot"]["verified"] and c["hotspot"]["shared_landmarks"] >= m["graph"]["min_shared_landmarks"] for c in t["connections"])
    assert t["validation"]["passed"]


def test_tour_retains_viewpoints_when_no_pair_shares_features(tmp_path, monkeypatch):
    work = _recon_dir(tmp_path, monkeypatch, [i * 0.5 for i in range(6)], [range(i * 100, i * 100 + 60) for i in range(6)])
    result = tour.build("jobs/x/recon", False)
    manifest = json.loads((work / "tour_manifest.json").read_text())

    assert len(result["nodes"]) == 6
    assert result["connections"] == []
    assert manifest["graph"]["components_found"] == 6
    assert manifest["graph"]["viewpoints_left_out"] == 0
    assert result["validation"]["passed"]


def test_tour_without_landmark_artifacts_publishes_only_unconnected_nodes(tmp_path, monkeypatch):
    work = _recon_dir(tmp_path, monkeypatch, [i * 0.5 for i in range(5)], [range(i * 100, i * 100 + 60) for i in range(5)])
    (work / "observations.json").unlink()
    (work / "points_full.npz").unlink()

    result = tour.build("jobs/x/recon", False)
    manifest = json.loads((work / "tour_manifest.json").read_text())

    assert len(result["nodes"]) == 5
    assert result["connections"] == []
    assert manifest["graph"]["components_found"] == 5
    assert any("Feature observations and a sparse point cloud are unavailable" in warning for warning in manifest["warnings"])
