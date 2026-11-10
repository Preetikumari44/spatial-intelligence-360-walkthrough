"""Pure geometry helpers: COLMAP model parsing, world normalisation, panorama maths, projection."""
import math

import cv2
import numpy as np

CAMERA_PARAM_LAYOUT = {
    "SIMPLE_PINHOLE": ("f", "cx", "cy"),
    "SIMPLE_RADIAL": ("f", "cx", "cy", "k"),
    "RADIAL": ("f", "cx", "cy", "k1", "k2"),
    "PINHOLE": ("fx", "fy", "cx", "cy"),
    "OPENCV": ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2"),
}


def quat_to_rot(qw, qx, qy, qz):
    n = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    qw, qx, qy, qz = qw / n, qx / n, qy / n, qz / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])


def parse_cameras(text):
    cams = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split()
        cid, model, w, h = int(p[0]), p[1], int(p[2]), int(p[3])
        names = CAMERA_PARAM_LAYOUT.get(model)
        if names is None:
            raise ValueError(f"unsupported COLMAP camera model {model}")
        vals = dict(zip(names, map(float, p[4:])))
        fx = vals.get("fx", vals.get("f"))
        fy = vals.get("fy", vals.get("f"))
        cams[cid] = {"w": w, "h": h, "fx": fx, "fy": fy, "cx": vals["cx"], "cy": vals["cy"]}
    return cams


def parse_images(text):
    """Return {name: {center, axes, camera_id}}. axes rows are the camera x/y/z axes in world coordinates."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    out = {}
    for i in range(0, len(lines) - 1, 2):
        p = lines[i].split()
        if len(p) < 10:
            continue
        qw, qx, qy, qz, tx, ty, tz = map(float, p[1:8])
        R = quat_to_rot(qw, qx, qy, qz)  # world -> camera
        t = np.array([tx, ty, tz])
        out[p[9]] = {"center": (-R.T @ t), "axes": R, "camera_id": int(p[8])}
    return out


def parse_points(text, max_error=1.5, min_track=3):
    pts, cols = [], []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split()
        track_len = (len(p) - 8) // 2
        if float(p[7]) > max_error or track_len < min_track:
            continue
        pts.append([float(p[1]), float(p[2]), float(p[3])])
        cols.append([int(p[4]), int(p[5]), int(p[6])])
    return np.array(pts).reshape(-1, 3), np.array(cols, dtype=np.uint8).reshape(-1, 3)


def parse_points_ex(text, max_error=1.5, min_track=3):
    """Like parse_points, but also returns each kept point's COLMAP POINT3D_ID (needed to know which image saw which landmark)."""
    pts, cols, ids = [], [], []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split()
        track_len = (len(p) - 8) // 2
        if float(p[7]) > max_error or track_len < min_track:
            continue
        ids.append(int(p[0]))
        pts.append([float(p[1]), float(p[2]), float(p[3])])
        cols.append([int(p[4]), int(p[5]), int(p[6])])
    return np.array(pts).reshape(-1, 3), np.array(cols, dtype=np.uint8).reshape(-1, 3), ids


def parse_image_observations(text):
    """{image name: set of POINT3D_IDs that the image observes}, read from the second line of every images.txt entry."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    out = {}
    for i in range(0, len(lines) - 1, 2):
        p = lines[i].split()
        if len(p) < 10:
            continue
        q = lines[i + 1].split()
        out[p[9]] = {int(q[k]) for k in range(2, len(q), 3) if int(q[k]) >= 0}
    return out


def world_normalisation(centers, axes, points):
    """
    COLMAP's world frame is arbitrary. Build one with +Y up and the ground axes aligned to the
    scene's main direction. Up comes from the cameras: image-y points down, so up is the mean of -y_axis.
    Returns (Rn, origin) with p_new = Rn @ (p - origin).
    """
    up = -np.mean([a[1] for a in axes], axis=0)
    up /= np.linalg.norm(up)
    ref = points if len(points) >= 50 else centers
    c = ref - ref.mean(axis=0)
    flat = c - np.outer(c @ up, up)
    _, _, vt = np.linalg.svd(flat, full_matrices=False)
    x = vt[0] - (vt[0] @ up) * up
    x /= np.linalg.norm(x)
    z = np.cross(x, up)
    return np.stack([x, up, z]), np.mean(centers, axis=0)


def phi(v):
    """Clockwise-from-above angle of a direction in the normalised frame (y up, ground = x/z)."""
    return math.atan2(v[2], v[0])


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def circular_mean(angles):
    return math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles))


def project(point, center, axes, cam):
    """Project a world point into a camera. Returns (u, v, depth) in pixels; lens distortion is ignored."""
    c = axes @ (np.asarray(point) - np.asarray(center))
    if c[2] <= 1e-9:
        return None, None, float(c[2])
    return cam["fx"] * c[0] / c[2] + cam["cx"], cam["fy"] * c[1] / c[2] + cam["cy"], float(c[2])


def equirect_to_persp(img, yaw_deg, fov_deg=90.0, size=960):
    """Render a pinhole view out of an equirectangular frame. Yaw is positive to the right."""
    f = 0.5 * size / math.tan(math.radians(fov_deg) / 2)
    xs, ys = np.meshgrid(np.arange(size) - size / 2 + 0.5, np.arange(size) - size / 2 + 0.5)
    d = np.stack([xs, ys, np.full_like(xs, f)], axis=-1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    psi = math.radians(yaw_deg)
    xr = d[..., 0] * math.cos(psi) + d[..., 2] * math.sin(psi)
    zr = -d[..., 0] * math.sin(psi) + d[..., 2] * math.cos(psi)
    lon = np.arctan2(xr, zr)
    lat = np.arcsin(np.clip(-d[..., 1], -1, 1))
    h, w = img.shape[:2]
    map_x = ((lon / (2 * math.pi) + 0.5) * w).astype(np.float32)
    map_y = ((0.5 - lat / math.pi) * h).astype(np.float32)
    return cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
