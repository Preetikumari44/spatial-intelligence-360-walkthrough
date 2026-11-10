"""
A small synthetic room (floor, ceiling, three walls, random texture) rendered by ray casting.
Gives the SfM, TSDF and Gaussian tests a scene whose true camera poses and true depth are known.
Used by tests only; the production pipeline never touches it.
"""
import cv2
import numpy as np

W, H, F = 480, 360, 420.0
ROOM = {"x": (-3.0, 3.0), "y": (0.0, 3.0), "z": (-2.0, 6.0)}


def _texture(seed, size=1024):
    rng = np.random.default_rng(seed)
    tex = np.zeros((size, size), np.float32)
    for sigma, weight in ((2.0, 1.0), (6, 1.4), (16, 1.2)):
        tex += weight * cv2.GaussianBlur(rng.random((size, size)).astype(np.float32), (0, 0), sigma) / (sigma ** 0.3)
    tex = (tex - tex.min()) / (tex.max() - tex.min())
    colour = np.stack([tex, np.roll(tex, 97, 0) * 0.8 + 0.1, np.roll(tex, 211, 1) * 0.7 + 0.15], -1)
    return (colour * 255).astype(np.uint8)


_TEX = {}


def look_at(centre, target, up=(0, 1, 0)):
    f = np.asarray(target, float) - np.asarray(centre, float)
    f /= np.linalg.norm(f)
    r = np.cross(np.asarray(up, float), f)
    r /= np.linalg.norm(r)
    down = np.cross(r, f)
    return np.stack([r, down, f])  # world -> camera rotation


def render(centre, R, w=W, h=H, f=F):
    """Returns (bgr image, depth along the camera z axis)."""
    if not _TEX:
        for k in range(5):
            _TEX[k] = _texture(100 + k)
    u, v = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    d_cam = np.stack([(u - w / 2) / f, (v - h / 2) / f, np.ones_like(u)], -1)
    d = d_cam @ R  # rows are R^T d_cam
    c = np.asarray(centre, float)
    best = np.full((h, w), np.inf)
    plane = np.full((h, w), -1)
    planes = [(1, ROOM["y"][0]), (1, ROOM["y"][1]), (0, ROOM["x"][0]), (0, ROOM["x"][1]), (2, ROOM["z"][1])]
    ts = []
    for k, (axis, value) in enumerate(planes):
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (value - c[axis]) / d[..., axis]
        t = np.where(t > 1e-6, t, np.inf)
        ts.append(t)
        better = t < best
        best = np.where(better, t, best)
        plane = np.where(better, k, plane)
    pts = c + best[..., None] * d
    img = np.zeros((h, w, 3), np.uint8)
    scale = 55.0
    for k, (axis, _) in enumerate(planes):
        m = plane == k
        if not m.any():
            continue
        a, b = [i for i in range(3) if i != axis]
        mx = ((pts[..., a] * scale) % 1024).astype(np.float32)
        my = ((pts[..., b] * scale) % 1024).astype(np.float32)
        img[m] = cv2.remap(_TEX[k], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)[m]
    return img, best.astype(np.float32)


def camera_path(n=36):
    """A walk along the room with a gentle sideways swing and a slow head turn."""
    out = []
    for i in range(n):
        s = i / (n - 1)
        centre = np.array([1.2 * np.sin(2.2 * s), 1.5 + 0.05 * np.sin(5 * s), -1.0 + 2.6 * s])
        target = np.array([0.9 * np.sin(3.0 * s + 0.5), 1.4, 5.0])
        out.append((centre, look_at(centre, target)))
    return out


def render_sequence(n=36):
    frames, depths, poses = [], [], camera_path(n)
    for c, R in poses:
        img, depth = render(c, R)
        frames.append(img)
        depths.append(depth)
    return frames, depths, poses


def write_frames(directory, frames, fps=3.0):
    """Writes frames + frames.json in the layout the AI service expects. Returns the frame list."""
    import json
    directory.mkdir(parents=True, exist_ok=True)
    meta = []
    for i, img in enumerate(frames):
        name = f"f_{i * 10:06d}.jpg"
        cv2.imwrite(str(directory / name), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        meta.append({"file": f"{directory.name}/{name}", "name": name, "frame_index": i * 10, "t": round(i / fps, 3), "blur": 100.0})
    (directory / "frames.json").write_text(json.dumps({"summary": {}, "frames": meta}))
    return meta


def umeyama(src, dst):
    """Similarity transform (scale, R, t) mapping src onto dst, used to compare recovered vs true camera centres."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s0, d0 = src - mu_s, dst - mu_d
    cov = d0.T @ s0 / len(src)
    U, S, Vt = np.linalg.svd(cov)
    D = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[2, 2] = -1
    R = U @ D @ Vt
    scale = (S * np.diag(D)).sum() / s0.var(0).sum()
    t = mu_d - scale * R @ mu_s
    return scale, R, t
