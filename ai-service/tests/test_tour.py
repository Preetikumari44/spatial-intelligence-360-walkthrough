"""Tour generation from real registered camera poses (OpenCV SfM on a synthetic room with known poses)."""
import json
import shutil

import numpy as np
import pytest

import synth
from app import config, jobs, reconstruct, tour
from app.errors import PipelineError


def _build(tmp_path, monkeypatch, n=24, tag="tour"):
    monkeypatch.setattr(config, "SFM_BACKEND", "opencv")
    frames, _, _ = synth.render_sequence(n)
    fdir = config.resolve(f"jobs/{tag}/frames")
    if fdir.exists():
        shutil.rmtree(fdir)
    synth.write_frames(fdir, frames)
    # write_frames stores "file" relative to the folder name; the service stores it relative to STORAGE_ROOT
    meta = json.loads((fdir / "frames.json").read_text())
    for f in meta["frames"]:
        f["file"] = f"jobs/{tag}/frames/{f['name']}"
    (fdir / "frames.json").write_text(json.dumps(meta))
    reconstruct.run(f"jobs/{tag}/frames", f"jobs/{tag}/recon", False, jobs.get(None))
    return tour.build(f"jobs/{tag}/recon", False), json.loads((config.resolve(f"jobs/{tag}/recon") / "reconstruction.json").read_text())


def test_tour_nodes_come_from_registered_poses_and_real_frames(tmp_path, monkeypatch):
    t, recon = _build(tmp_path, monkeypatch)
    nodes = t["nodes"]
    assert len(nodes) >= 3
    pos = np.array([n["position"] for n in nodes])
    assert np.ptp(pos, axis=0).max() > 0.1                      # camera positions are not all identical
    registered = {f["file"] for f in recon["frames"] if f["registered"]}
    assert all(n["frame"] in registered for n in nodes)         # every viewpoint is an actually registered source frame
    assert all((config.resolve(n["frame"])).is_file() for n in nodes)
    centers = {recon["images"][f["name"]]["center"].__repr__() for f in recon["frames"] if f["registered"]}
    assert all(any(np.allclose(n["position"], json.loads(c), atol=1e-4) for c in centers) for n in nodes)  # positions == SfM centres
    assert all(n["time_sec"] is not None and n["camera"] and n["panorama"] is False for n in nodes)   # timestamps kept; flat video is not a panorama
    times = [n["time_sec"] for n in nodes]
    assert times == sorted(times)


def test_navigation_graph_is_connected_and_symmetric(tmp_path, monkeypatch):
    t, _ = _build(tmp_path, monkeypatch, tag="tour2")
    ids = {n["id"] for n in t["nodes"]}
    edges = {(c["from"], c["to"]) for c in t["connections"]}
    assert all(a in ids and b in ids and a != b for a, b in edges)
    assert all((b, a) in edges for a, b in edges)
    seen, todo = set(), [t["nodes"][0]["id"]]
    while todo:
        x = todo.pop()
        if x in seen:
            continue
        seen.add(x)
        todo += [b for a, b in edges if a == x]
    assert seen == ids                                           # every viewpoint is reachable
    for c in t["connections"]:
        h = c["hotspot"]
        assert np.isfinite(h.get("bearing", 0.0))
        if h.get("visible"):
            assert 0 <= h["x"] <= 1 and 0 <= h["y"] <= 1
    m = json.loads((config.resolve(t["manifest_path"])).read_text())
    assert m["coverage"]["registered_images"] > 0 and m["is_360"] is False and m["warnings"]
    assert isinstance(m["coverage"]["untracked_time_ranges_sec"], list)
    assert m["coverage"]["registered_images"] <= m["coverage"]["total_images"]
    assert 0 <= m["coverage"]["registered_fraction"] <= 1


def test_hotspot_uses_a_shared_landmark_visible_in_both_real_camera_views():
    camera = {"w": 640, "h": 480, "fx": 500.0, "fy": 500.0, "cx": 320.0, "cy": 240.0}
    a = {"center": np.array([0.0, 0.0, 0.0]), "heading": 0.0, "axes": np.eye(3),
         "camera": camera, "landmarks": {0}}
    b = {"center": np.array([0.2, 0.0, 0.0]), "heading": 0.0, "axes": np.eye(3),
         "camera": camera, "landmarks": {0}}

    marker = tour.hotspot(a, b, np.array([[1.0, 0.0, 5.0]]))

    assert marker["visible"] is True
    assert marker["method"] == "shared-landmark"
    assert marker["landmark_index"] == 0
    assert marker["x"] == pytest.approx(420 / 640)
    assert marker["y"] == pytest.approx(0.5)


def test_equirectangular_hotspot_uses_viewer_yaw_and_pitch_conventions():
    a = {"center": np.array([0.0, 0.0, 0.0]), "heading": np.pi / 2, "camera": None}
    b = {"center": np.array([1.0, 1.0, 0.0])}

    marker = tour.hotspot(a, b)

    assert marker["yaw"] == pytest.approx(-np.pi / 2)
    assert marker["pitch"] == pytest.approx(np.pi / 4)
    assert marker["directional"] is True


def test_only_near_complete_low_parallax_sphere_is_attached_to_a_pose_viewpoint(monkeypatch):
    nodes = [
        {"id": "n0", "position": [0.0, 0.0, 0.0], "frame": "frames/a.jpg", "panorama": False, "heading_rad": 0.0},
        {"id": "n1", "position": [1.0, 0.0, 0.0], "frame": "frames/b.jpg", "panorama": False, "heading_rad": 0.0},
    ]
    connections = [{"from": "n0", "to": "n1", "hotspot": {"verified": True, "inliers": 10}}]
    meta = {
        "file": "pano_000.jpg", "status": "full_sphere", "is_complete_360": True,
        "coverage": {"sphere_area": 0.999, "horizon_band": 1.0},
        "center_spread_ratio": 0.002, "center": [0.0, 0.0, 0.0],
        "basis_world": {"forward": [0.0, 0.0, 1.0], "right": [1.0, 0.0, 0.0], "up": [0.0, 1.0, 0.0]},
    }
    monkeypatch.setattr(tour.panorama, "build_all", lambda _: {"panoramas": [meta], "skipped": []})

    coverage, _ = tour._attach_panorama_viewpoints("jobs/pano/work", nodes, connections, 2.0)

    assert coverage["status"] == "available" and coverage["viewpoints"] == 1
    assert nodes[0]["frame"] == "jobs/pano/work/panoramas/pano_000.jpg"
    assert nodes[0]["panorama"] is True
    assert connections[0]["hotspot"]["method"] == "reconstructed-panorama"
    assert connections[0]["hotspot"]["directional"] is True
    assert connections[0]["hotspot"]["yaw"] == pytest.approx(np.pi / 2, abs=1e-4)


def test_horizontal_only_panorama_is_not_exposed_as_a_spherical_view(monkeypatch):
    nodes = [{"id": "n0", "position": [0.0, 0.0, 0.0], "frame": "frames/a.jpg", "panorama": False}]
    meta = {
        "file": "pano_000.jpg", "status": "horizontal_360", "is_complete_360": False,
        "coverage": {"sphere_area": 0.7, "horizon_band": 1.0},
        "center_spread_ratio": 0.002, "center": [0.0, 0.0, 0.0],
        "basis_world": {"forward": [0.0, 0.0, 1.0]},
    }
    monkeypatch.setattr(tour.panorama, "build_all", lambda _: {"panoramas": [meta], "skipped": []})

    coverage, _ = tour._attach_panorama_viewpoints("jobs/pano/work", nodes, [], 2.0)

    assert coverage["status"] == "partial"
    assert coverage["best_candidate_sphere_area_coverage"] == pytest.approx(0.7)
    assert coverage["best_candidate_horizon_band_coverage"] == pytest.approx(1.0)
    assert nodes[0]["frame"] == "frames/a.jpg" and nodes[0]["panorama"] is False


def test_partial_or_high_parallax_panorama_is_not_exposed_as_360(monkeypatch):
    nodes = [{"id": "n0", "position": [0.0, 0.0, 0.0], "frame": "frames/a.jpg", "panorama": False}]
    candidates = [{
        "file": "pano_000.jpg", "status": "partial", "is_complete_360": False,
        "center_spread_ratio": 0.002, "center": [0.0, 0.0, 0.0],
        "basis_world": {"forward": [0.0, 0.0, 1.0]},
    }, {
        "file": "pano_001.jpg", "status": "full_sphere", "is_complete_360": True,
        "coverage": {"sphere_area": 0.999, "horizon_band": 1.0},
        "center_spread_ratio": 0.02, "center": [0.0, 0.0, 0.0],
        "basis_world": {"forward": [0.0, 0.0, 1.0]},
    }]
    monkeypatch.setattr(tour.panorama, "build_all", lambda _: {"panoramas": candidates, "skipped": []})

    coverage, _ = tour._attach_panorama_viewpoints("jobs/pano/work", nodes, [], 2.0)

    assert coverage["status"] == "partial"
    assert nodes[0]["frame"] == "frames/a.jpg" and nodes[0]["panorama"] is False


def test_pose_tour_merge_keeps_unregistered_frames_as_unplaced_fallback_views():
    pose_nodes = [
        {"id": "p0", "source_frame": "frames/a.jpg", "frame": "frames/a.jpg", "position": [0.0, 0.0, 0.0],
         "heading_rad": 0.0, "camera": {"w": 10, "h": 10}, "panorama": False},
        {"id": "p2", "source_frame": "frames/c.jpg", "frame": "frames/c.jpg", "position": [2.0, 0.0, 0.0],
         "heading_rad": 0.0, "camera": {"w": 10, "h": 10}, "panorama": False},
    ]
    pose_connections = [{"from": "p0", "to": "p2", "hotspot": {"verified": True}, "distance": 2.0}]
    fallback_nodes = [
        {"id": "v0", "seq": 0, "label": "Viewpoint 01", "frame": "frames/a.jpg", "time_sec": 0.0},
        {"id": "v1", "seq": 1, "label": "Viewpoint 02", "frame": "frames/b.jpg", "time_sec": 1.0},
        {"id": "v2", "seq": 2, "label": "Viewpoint 03", "frame": "frames/c.jpg", "time_sec": 2.0},
    ]
    fallback_connections = [
        {"from": "v0", "to": "v1", "hotspot": {"verified": True}},
        {"from": "v1", "to": "v2", "hotspot": {"verified": True}},
    ]

    nodes, connections, summary = tour._merge_video_fallback(
        pose_nodes, pose_connections, {"nodes": fallback_nodes, "connections": fallback_connections})

    assert [node["id"] for node in nodes] == ["v0", "v1", "v2"]
    assert nodes[0]["has_pose"] is True and nodes[0]["position"] == [0.0, 0.0, 0.0]
    assert nodes[1]["has_pose"] is False and nodes[1]["position"] is None
    assert summary["pose_viewpoints"] == 2 and summary["fallback_viewpoints"] == 1
    assert {(link["from"], link["to"]) for link in connections} == {
        ("v0", "v2"), ("v0", "v1"), ("v1", "v2"),
    }


def test_manifest_coverage_contract_is_generated_without_reconstruction(tmp_path, monkeypatch):
    work = tmp_path / "recon"
    work.mkdir()
    frames = [
        {"stem": f"f{i}", "name": f"f{i}.jpg", "file": f"frames/f{i}.jpg", "t": float(i),
         "frame_index": i, "registered": i != 1}
        for i in range(4)
    ]
    images = {
        f"f{i}.jpg": {"center": [float(i), 0.0, 0.0], "axes": np.eye(3).tolist(), "camera_id": 1}
        for i in (0, 2, 3)
    }
    recon = {
        "is_360": False,
        "frames": frames,
        "images": images,
        "cameras": {"1": {"w": 100, "h": 80, "fx": 90, "fy": 90, "cx": 50, "cy": 40}},
        "extents": {"x": 3.0, "y": 1.0, "z": 1.0},
    }
    (work / "reconstruction.json").write_text(json.dumps(recon))
    (work / "points_preview.json").write_text(json.dumps({"positions": []}))
    # the registered frames saw the same 40 landmarks (this fixture has no coordinates for them, so only the overlap is checked)
    (work / "observations.json").write_text(json.dumps({"version": 1, "landmarks": 40, "images": {f"f{i}.jpg": list(range(40)) for i in (0, 2, 3)}}))
    monkeypatch.setattr(config, "resolve", lambda _: work)

    result = tour.build("jobs/coverage/recon", False)
    manifest = json.loads((work / "tour_manifest.json").read_text())
    coverage = manifest["coverage"]

    assert len(result["nodes"]) >= 2
    assert coverage == {
        "registered_fraction": 0.75,
        "registered_images": 3,
        "total_images": 4,
        "untracked_time_ranges_sec": [[1.0, 2.0]],
    }


def test_tour_refuses_when_the_camera_never_moved(tmp_path):
    work = config.resolve("jobs/tour_static/recon")
    work.mkdir(parents=True, exist_ok=True)
    img = {"center": [0, 0, 0], "axes": np.eye(3).tolist(), "camera_id": 1}
    recon = {"is_360": False, "units": "model_units", "cameras": {"1": {"w": 100, "h": 80, "fx": 90, "fy": 90, "cx": 50, "cy": 40}},
             "images": {f"f{i}.jpg": img for i in range(6)}, "extents": {"x": 0, "y": 0, "z": 0},
             "frames": [{"stem": f"f{i}", "name": f"f{i}.jpg", "file": f"x/f{i}.jpg", "t": i, "frame_index": i, "registered": True} for i in range(6)],
             "registered_images": 6, "total_images": 6, "point_count": 0}
    (work / "reconstruction.json").write_text(json.dumps(recon))
    (work / "points_preview.json").write_text(json.dumps({"positions": []}))
    with pytest.raises(PipelineError, match="did not move"):
        tour.build("jobs/tour_static/recon", False)
