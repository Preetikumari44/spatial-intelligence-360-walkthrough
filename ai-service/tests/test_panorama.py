"""Panorama stitching from known poses: ground truth is an equirectangular image that perspective views are cut out of."""
import math

import cv2
import numpy as np
import pytest

from app import geometry, panorama

SIZE = 480
FOCAL = 0.5 * SIZE / math.tan(math.radians(90.0) / 2)
CAM = {"w": SIZE, "h": SIZE, "fx": FOCAL, "fy": FOCAL, "cx": SIZE / 2, "cy": SIZE / 2}


def _truth(w=1536):
    rng = np.random.default_rng(4)
    t = cv2.resize(rng.integers(0, 255, (96, 192, 3), dtype=np.uint8), (w, w // 2), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(t, (0, 0), 5.0)


def _view(truth, yaw_deg, center=(0.0, 0.0, 0.0), gain=1.0):
    psi = math.radians(yaw_deg)
    img = geometry.equirect_to_persp(truth, yaw_deg, 90.0, SIZE)
    M = np.array([[math.cos(psi), 0, math.sin(psi)], [0, -1, 0], [-math.sin(psi), 0, math.cos(psi)]])   # camera -> world as in equirect_to_persp
    return {"image": np.clip(img * gain, 0, 255).astype(np.uint8), "center": np.array(center, float), "axes": M.T, "camera": CAM,
            "frame": f"y{yaw_deg}", "t": yaw_deg / 30.0}


def test_surrounding_views_give_a_horizontal_360_panorama_that_matches_the_scene(tmp_path):
    truth = _truth()
    group = [_view(truth, y) for y in range(0, 360, 30)]
    meta = panorama.build(group, tmp_path / "p.png", width=1536)
    assert meta["status"] == "horizontal_360" and meta["is_complete_360"] is False
    assert meta["coverage"]["horizon_band"] >= 0.995 and meta["coverage"]["sphere_area"] < panorama.FULL_SPHERE_MIN   # floor / ceiling were not filmed
    pano = cv2.imread(str(tmp_path / "p.png"))
    mask = cv2.imread(str(tmp_path / "p_mask.png"), 0) > 0
    # the reference renderer (equirect_to_persp) samples at pixel corners, a sub-pixel offset: compare after a small blur
    blur = lambda a: cv2.GaussianBlur(a.astype(np.float32), (0, 0), 3.0)  # noqa: E731
    inner = cv2.erode(mask.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0     # away from the empty border where blur mixes in black
    err = np.abs(blur(pano) - blur(truth)).mean(axis=2)[inner]
    assert np.median(err) < 5.0 and err.mean() < 9.0                        # real pixels, in the right place
    assert not mask.all() and (pano[~mask] == 0).all()                      # unseen regions stay empty, nothing invented
    assert meta["generated_regions"].startswith("none") and meta["seam_error_gray_levels"] < 8.0


def test_a_narrow_sweep_is_labelled_partial_not_360(tmp_path):
    truth = _truth()
    meta = panorama.build([_view(truth, y) for y in (0, 30, 60, 90)], tmp_path / "q.png", width=1536)
    assert meta["status"] == "partial" and meta["is_complete_360"] is False and "not a 360" in meta["note"]
    assert meta["coverage"]["horizon_band"] < 0.6 and meta["confidence"] < 0.5


def test_one_flat_frame_is_never_stretched_into_a_panorama(tmp_path):
    meta = panorama.build([_view(_truth(), 0)], tmp_path / "r.png", width=1024)
    assert meta["status"] == "partial" and meta["coverage"]["horizon_band"] < 0.35


def test_exposure_differences_are_matched_across_views(tmp_path):
    truth = _truth()
    group = [_view(truth, y, gain=(0.7 if i % 2 else 1.0)) for i, y in enumerate(range(0, 360, 30))]
    meta = panorama.build(group, tmp_path / "e.png", width=1536)
    assert meta["seam_error_gray_levels"] < 25.0 and meta["status"] == "horizontal_360"
    assert meta["is_complete_360"] is False


def test_hotspot_direction_comes_from_relative_camera_positions(tmp_path):
    truth = _truth()
    meta = panorama.build([_view(truth, y) for y in range(0, 360, 30)], tmp_path / "h.png", width=1024)
    ahead = panorama.hotspot_for(meta, [0.0, 0.0, 2.0])      # in the direction frame 0 looks at
    assert abs(ahead["yaw"]) < 1e-3 and abs(ahead["x"] - 0.5) < 1e-3
    right = panorama.hotspot_for(meta, [3.0, 0.0, 0.0])
    assert abs(right["yaw"] - math.pi / 2) < 1e-3 and abs(right["x"] - 0.75) < 1e-3
    back = panorama.hotspot_for(meta, [0.0, 0.0, -1.0])
    assert abs(abs(back["yaw"]) - math.pi) < 1e-3
    assert panorama.hotspot_for(meta, meta["center"]) is None


def test_grouping_by_camera_position():
    mk = lambda p: {"center": np.array(p, float)}  # noqa: E731
    g = panorama.group_candidates([mk([0, 0, 0]), mk([0.02, 0, 0]), mk([5, 0, 0]), mk([5.01, 0, 0]), mk([0.01, 0.01, 0])], radius=0.1)
    assert sorted(len(x) for x in g) == [2, 3]


def test_build_all_on_a_reconstruction_with_a_real_rendered_room(tmp_path):
    """A camera that turns on the spot inside the synthetic room, plus a walk elsewhere: one panorama (partial: the room has no back wall filmed)."""
    import json

    import synth
    from app import config
    work_rel, frames_rel = "jobs/pano_all/work", "jobs/pano_all/frames"
    fdir = config.resolve(frames_rel)
    fdir.mkdir(parents=True, exist_ok=True)
    (config.resolve(work_rel)).mkdir(parents=True, exist_ok=True)
    centre = np.array([0.0, 1.5, 1.0])
    poses = [(centre, synth.look_at(centre, centre + [math.sin(a), 0, math.cos(a)])) for a in np.radians(np.arange(-50, 51, 20))]
    poses += [(np.array([2.0 + 0.5 * i, 1.5, 3.0]), synth.look_at([2.0 + 0.5 * i, 1.5, 3.0], [2.0 + 0.5 * i, 1.5, 6.0])) for i in range(3)]
    frames, images = [], {}
    for i, (c, R) in enumerate(poses):
        img, _ = synth.render(c, R)
        name = f"f_{i:03d}.jpg"
        cv2.imwrite(str(fdir / name), img)
        frames.append({"stem": name[:-4], "name": name, "file": f"{frames_rel}/{name}", "t": float(i), "frame_index": i, "registered": True})
        images[name] = {"center": c.tolist(), "axes": R.tolist(), "camera_id": 1}
    cam = {"w": synth.W, "h": synth.H, "fx": synth.F, "fy": synth.F, "cx": synth.W / 2, "cy": synth.H / 2}
    (config.resolve(work_rel) / "reconstruction.json").write_text(json.dumps({"is_360": False, "cameras": {"1": cam}, "images": images, "frames": frames}))
    res = panorama.build_all(work_rel, min_frames=5, width=1024)
    assert len(res["panoramas"]) == 1 and any("only" in s for s in res["skipped"])        # the walk elsewhere is too sparse for a panorama
    m = res["panoramas"][0]
    assert m["status"] == "partial" and m["is_complete_360"] is False and m["source_frames"] and len(m["source_frames"]) == 6
    assert (config.resolve(work_rel) / "panoramas" / m["file"]).is_file()


def test_sensor_report_is_honest_for_a_plain_video_and_reads_a_gps_tag(tmp_path):
    import subprocess

    from app import sensors
    src = tmp_path / "plain.mp4"
    subprocess.run(["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5", "-t", "1", str(src)], check=True)
    r = sensors.inspect(src)
    assert r["gps"] is None and r["motion_streams"] == [] and r["compass_heading"] is None and r["fusion_used"] is False
    tagged = tmp_path / "gps.mp4"
    subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(src), "-c", "copy", "-metadata", "location=+12.9716+077.5946/", str(tagged)], check=True)
    g = sensors.inspect(tagged)["gps"]
    assert g and abs(g["latitude"] - 12.9716) < 1e-6 and abs(g["longitude"] - 77.5946) < 1e-6
