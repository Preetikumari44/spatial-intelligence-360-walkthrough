"""
Panoramas from ordinary video, built only from real captured pixels.

Frames whose camera centres are (nearly) the same point are grouped. Each frame, with its SfM rotation and intrinsics, is warped onto an
equirectangular 2:1 canvas, exposure-matched and feather-blended. Nothing is invented:

  * pixels no frame saw stay empty (the mask is saved) - there is no inpainting and no stretching of a single flat frame;
  * the result is labelled by what was really covered:
        full_sphere     >= 99.5 % of the sphere (area weighted)
        horizontal_360  the whole horizon band (+-20 deg) is covered, floor/ceiling are not
        partial         anything less: a wide view, NOT a 360 panorama
  * every panorama carries coverage, a ghosting/seam error measured on the overlaps, the camera-centre spread (parallax risk) and a confidence.

Hotspot directions for a panorama come from the relative camera positions expressed in the panorama's own axes (hotspot_for).
"""
import json
import math
from pathlib import Path

import cv2
import numpy as np

HORIZON_BAND_DEG = 20.0
FULL_SPHERE_MIN = 0.995


def group_candidates(cands, radius):
    """Greedy clustering of frames whose camera centres lie within `radius` of the group's first frame."""
    groups = []
    for c in cands:
        for g in groups:
            if np.linalg.norm(c["center"] - g[0]["center"]) <= radius:
                g.append(c)
                break
        else:
            groups.append([c])
    return groups


def _basis(group):
    """Panorama axes in world coordinates: right, up, forward (forward = first frame's viewing direction on the horizon)."""
    up = -np.mean([c["axes"][1] for c in group], axis=0)
    up /= np.linalg.norm(up)
    x0 = np.asarray(group[0]["axes"][0], float)
    right = x0 - (x0 @ up) * up
    right /= np.linalg.norm(right)
    z0 = np.asarray(group[0]["axes"][2], float)
    fwd = z0 - (z0 @ up) * up - (z0 @ right) * right
    n = np.linalg.norm(fwd)
    if n < 1e-6:                                   # the first frame looks straight up or down: pick any horizontal direction
        fwd = np.cross(right, up)
    else:
        fwd /= n
    return right, up, fwd


def build(group, out_png, width=2048, name="pano"):
    """
    group: list of {"image": BGR array, "center", "axes" (3x3 world->camera), "camera": {fx, fy, cx, cy, w, h}, "frame": id, "t": seconds}.
    Returns the metadata dict; the panorama is written to out_png (and a mask next to it).
    """
    right, up, fwd = _basis(group)
    W, H = width, width // 2
    lon = (np.arange(W) + 0.5) / W * 2 * math.pi - math.pi
    lat = math.pi / 2 - (np.arange(H) + 0.5) / H * math.pi
    LON, LAT = np.meshgrid(lon, lat)
    local = np.stack([np.cos(LAT) * np.sin(LON), np.sin(LAT), np.cos(LAT) * np.cos(LON)], -1)
    d_world = local[..., 0:1] * right + local[..., 1:2] * up + local[..., 2:3] * fwd

    acc = np.zeros((H, W, 3), np.float64)
    wsum = np.zeros((H, W), np.float64)
    sq = np.zeros((H, W), np.float64)
    count = np.zeros((H, W), np.int32)
    used = []
    for g in group:
        img, R, cam = g["image"], np.asarray(g["axes"], float), g["camera"]
        h, w = img.shape[:2]
        sx, sy = w / cam["w"], h / cam["h"]
        dc = d_world @ R.T
        z = dc[..., 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = (cam["fx"] * dc[..., 0] / z + cam["cx"]) * sx
            v = (cam["fy"] * dc[..., 1] / z + cam["cy"]) * sy
        ok = (z > 0.05) & (u >= 0) & (u < w - 1) & (v >= 0) & (v < h - 1)
        if not ok.any():
            continue
        mx, my = np.where(ok, u, -1).astype(np.float32), np.where(ok, v, -1).astype(np.float32)
        warped = cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT).astype(np.float64)
        feather = np.minimum(np.minimum(np.arange(w) + 0.5, w - np.arange(w) - 0.5)[None, :],
                             np.minimum(np.arange(h) + 0.5, h - np.arange(h) - 0.5)[:, None]) / (0.5 * min(w, h))
        wt = cv2.remap(np.clip(feather, 0, 1).astype(np.float32), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT).astype(np.float64)
        wt = np.where(ok, wt, 0.0) + np.where(ok, 1e-4, 0.0)
        both = (wsum > 0) & (wt > 1e-3)
        if both.sum() > 200:                        # match exposure to what is already on the canvas
            gain = float(np.clip((acc[both].mean() / max(wsum[both].mean(), 1e-9)) / max(warped[both].mean(), 1e-9), 0.75, 1.33))
            warped *= gain
        acc += warped * wt[..., None]
        gray = warped.mean(axis=2)
        sq += gray * gray * wt
        wsum += wt
        count += (wt > 1e-3).astype(np.int32)
        used.append(g)
    if not used:
        raise ValueError("no frame projects onto the panorama")

    seen = wsum > 1e-3
    pano = np.zeros((H, W, 3), np.uint8)
    pano[seen] = np.clip(acc[seen] / wsum[seen, None], 0, 255).astype(np.uint8)
    area = np.cos(LAT)
    cov_area = float((area * seen).sum() / area.sum())
    band = np.abs(LAT) <= math.radians(HORIZON_BAND_DEG)
    cov_h = float(seen[band].mean())
    overlap = count >= 2
    seam = 0.0
    if overlap.any():
        mean_g = (acc[overlap].mean(axis=1)) / wsum[overlap]
        var = np.maximum(sq[overlap] / wsum[overlap] - mean_g ** 2, 0)
        seam = float(np.sqrt(var).mean())

    centers = np.array([g["center"] for g in used])
    spread = float(np.linalg.norm(centers - centers.mean(axis=0), axis=1).max())
    status = "full_sphere" if cov_area >= FULL_SPHERE_MIN else ("horizontal_360" if cov_h >= 0.995 else "partial")
    conf = (0.6 * cov_h + 0.4 * cov_area) * float(np.clip(1 - seam / 40.0, 0, 1))
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), pano, [cv2.IMWRITE_JPEG_QUALITY, 92] if out_png.suffix.lower() in (".jpg", ".jpeg") else [])
    cv2.imwrite(str(out_png.with_name(out_png.stem + "_mask.png")), (seen * 255).astype(np.uint8))
    meta = {
        "name": name, "file": out_png.name, "mask": out_png.stem + "_mask.png", "projection": "equirectangular", "size": [W, H],
        "status": status,
        "is_complete_360": status == "full_sphere",
        "coverage": {"sphere_area": round(cov_area, 4), "horizon_band": round(cov_h, 4), "horizon_band_deg": HORIZON_BAND_DEG},
        "seam_error_gray_levels": round(seam, 2), "center_spread_model_units": round(spread, 5),
        "confidence": round(float(conf), 3), "generated_regions": "none: unseen pixels are left empty (see mask)",
        "center": np.mean(centers, axis=0).tolist(),
        "basis_world": {"right": right.tolist(), "up": up.tolist(), "forward": fwd.tolist()},
        "source_frames": [{"frame": g.get("frame"), "t": g.get("t")} for g in used],
    }
    if status == "partial":
        meta["note"] = ("Partial view: the source frames do not surround the camera position. This is a wide reconstructed view, "
                        "not a 360-degree panorama.")
    elif status == "horizontal_360":
        meta["note"] = "The whole horizon is covered; floor and/or ceiling were not filmed and stay empty."
    return meta


def hotspot_for(meta, target_center):
    """Direction of another viewpoint as seen from this panorama: yaw/pitch in radians and the pixel position on the 2:1 image (0..1)."""
    b = meta["basis_world"]
    d = np.asarray(target_center, float) - np.asarray(meta["center"], float)
    n = np.linalg.norm(d)
    if n < 1e-9:
        return None
    x, y, z = d @ np.array(b["right"]), d @ np.array(b["up"]), d @ np.array(b["forward"])
    yaw, pitch = math.atan2(x, z), math.asin(float(np.clip(y / n, -1, 1)))
    return {"yaw": round(yaw, 4), "pitch": round(pitch, 4), "x": round(yaw / (2 * math.pi) + 0.5, 4), "y": round(0.5 - pitch / math.pi, 4),
            "distance": round(float(n), 5)}


def build_all(work_rel, out_rel=None, radius_frac=0.05, min_frames=6, width=2048):
    """
    Panoramas for every place in a reconstruction where enough frames were filmed from (nearly) the same position.
    Reads reconstruction.json (poses, intrinsics, frame files). Returns {"panoramas": [meta...], "skipped": [reason...]}.
    """
    from . import config                                   # imported here so the stitcher itself has no storage dependency
    work = config.resolve(work_rel)
    recon = json.loads((work / "reconstruction.json").read_text())
    if recon.get("is_360"):
        return {"panoramas": [], "skipped": ["360 source footage already is panoramic; nothing is stitched"]}
    frames = {f["name"]: f for f in recon["frames"]}
    cands = []
    for name, im in recon["images"].items():
        f = frames.get(name)
        img = cv2.imread(str(config.resolve(f["file"]))) if f else None
        if img is None:
            continue
        cands.append({"image": img, "center": np.array(im["center"], float), "axes": np.array(im["axes"], float),
                      "camera": recon["cameras"][str(im["camera_id"])], "frame": name, "t": f["t"]})
    if not cands:
        return {"panoramas": [], "skipped": ["no registered frame image could be read"]}
    centers = np.array([c["center"] for c in cands])
    extent = float(np.linalg.norm(centers.max(0) - centers.min(0))) or 1.0
    out = work / (out_rel or "panoramas")
    out.mkdir(parents=True, exist_ok=True)
    metas, skipped = [], []
    for k, g in enumerate(group_candidates(cands, radius_frac * extent)):
        if len(g) < min_frames:
            skipped.append(f"place {k + 1}: only {len(g)} frame(s) filmed from this position (need {min_frames}); no panorama")
            continue
        try:
            m = build(g, out / f"pano_{k:03d}.jpg", width, name=f"pano_{k:03d}")
        except ValueError as e:
            skipped.append(f"place {k + 1}: {e}")
            continue
        m["center_spread_ratio"] = round(m["center_spread_model_units"] / extent, 4)
        metas.append(m)
    (out / "panoramas.json").write_text(json.dumps({"panoramas": metas, "skipped": skipped}))
    return {"panoramas": metas, "skipped": skipped}
