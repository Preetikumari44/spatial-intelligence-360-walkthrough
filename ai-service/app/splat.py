"""
3D Gaussian Splatting: a small, genuinely CPU-capable *trainer* written in PyTorch, plus exporters and a preview renderer.

Training and rendering are different things. Training fits Gaussian parameters to the video frames by gradient descent
(this file). Rendering draws an existing Gaussian file; Open3D 0.20 can render splats (Vulkan needed) but cannot train them,
and CUDA-only gsplat is not used. The rasteriser here is a straightforward dense implementation meant for low resolution
(default 128 px) and a few thousand Gaussians: it will not match a CUDA implementation's quality or speed, and it has no
adaptive densification. The report states the iterations actually run and the PSNR before and after training.
"""
import gzip
import json
import logging
import math
import struct
import time
from pathlib import Path

import cv2
import numpy as np

from . import config, hardware, report
from .errors import Cancelled, PipelineError

log = logging.getLogger("splat")
SH_C0 = 0.28209479177387814


def _torch():
    try:
        import torch
        return torch
    except Exception as e:
        raise PipelineError(f"PyTorch is not installed, so Gaussian splats cannot be trained ({e}).", 503) from e


# ----------------------------------------------------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------------------------------------------------
class Gaussians:
    """Plain NumPy container: positions, log-scales, unit quaternions (w,x,y,z), opacity logits, RGB colours in 0..1."""

    def __init__(self, xyz, log_scale, quat, opacity_logit, rgb):
        self.xyz = np.asarray(xyz, np.float32)
        self.log_scale = np.asarray(log_scale, np.float32)
        q = np.asarray(quat, np.float32)
        self.quat = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
        self.opacity_logit = np.asarray(opacity_logit, np.float32).reshape(-1)
        self.rgb = np.clip(np.asarray(rgb, np.float32), 0, 1)

    def __len__(self):
        return len(self.xyz)

    def subset(self, mask):
        return Gaussians(self.xyz[mask], self.log_scale[mask], self.quat[mask], self.opacity_logit[mask], self.rgb[mask])


def _knn_scale(points):
    """Mean distance to the 3 nearest neighbours: a sensible initial footprint for each Gaussian."""
    from scipy.spatial import cKDTree
    d, _ = cKDTree(points).query(points, k=min(4, len(points)))
    return np.clip(d[:, 1:].mean(axis=1), 1e-4, None)


def initial_gaussians(points, colors, max_n, seed=0):
    rng = np.random.default_rng(seed)
    if len(points) > max_n:
        keep = rng.choice(len(points), max_n, replace=False)
        points, colors = points[keep], colors[keep]
    s = _knn_scale(points)
    n = len(points)
    return Gaussians(points, np.log(np.repeat(s[:, None], 3, axis=1) * 0.8), np.tile([1, 0, 0, 0], (n, 1)),
                     np.full(n, 0.0), np.asarray(colors, np.float32) / (255.0 if colors.dtype == np.uint8 else 1.0))


# ----------------------------------------------------------------------------------------------------------------------
# differentiable rasteriser (PyTorch, dense, chunked)
# ----------------------------------------------------------------------------------------------------------------------
def _quat_to_rot(q):
    torch = _torch()
    q = q / q.norm(dim=1, keepdim=True).clamp_min(1e-9)
    w, x, y, z = q.unbind(1)
    return torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
                        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
                        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], 1).reshape(-1, 3, 3)


def render(params, view, chunk=1024):
    """
    params: dict of torch tensors (xyz, log_scale, quat, opacity_logit, rgb_logit).
    view: dict with R (3x3 world->cam), centre (3), fx, fy, cx, cy, w, h (torch tensors / ints on the same device).
    Returns an (h, w, 3) image in 0..1 over a black background.
    """
    torch = _torch()
    from torch.utils.checkpoint import checkpoint
    R, c = view["R"], view["centre"]
    w, h = view["w"], view["h"]
    pc = (params["xyz"] - c) @ R.T
    z = pc[:, 2]
    keep = z > 0.05
    idx = torch.nonzero(keep).squeeze(1)
    pc, z = pc[idx], z[idx]
    xyz_scale = params["log_scale"][idx].exp()
    Rg = _quat_to_rot(params["quat"][idx])
    M = Rg * xyz_scale[:, None, :]
    sigma = M @ M.transpose(1, 2)
    zi = z.clamp_min(0.05)
    zero = torch.zeros_like(zi)
    J = torch.stack([view["fx"] / zi, zero, -view["fx"] * pc[:, 0] / zi ** 2,
                     zero, view["fy"] / zi, -view["fy"] * pc[:, 1] / zi ** 2], 1).reshape(-1, 2, 3)
    T = J @ R
    cov = T @ sigma @ T.transpose(1, 2)
    a = cov[:, 0, 0] + 0.3
    b = cov[:, 0, 1]
    d = cov[:, 1, 1] + 0.3
    det = (a * d - b * b).clamp_min(1e-8)
    inv_a, inv_b, inv_d = d / det, -b / det, a / det
    mu_x = view["fx"] * pc[:, 0] / zi + view["cx"]
    mu_y = view["fy"] * pc[:, 1] / zi + view["cy"]
    rad = 3.0 * torch.sqrt(torch.maximum(a, d))
    on_screen = (mu_x + rad > 0) & (mu_x - rad < w) & (mu_y + rad > 0) & (mu_y - rad < h)
    sel = torch.nonzero(on_screen).squeeze(1)
    if len(sel) == 0:
        return torch.zeros(h, w, 3, device=z.device)
    order = sel[torch.argsort(z[sel])]  # near to far
    mu_x, mu_y, inv_a, inv_b, inv_d = mu_x[order], mu_y[order], inv_a[order], inv_b[order], inv_d[order]
    opacity = torch.sigmoid(params["opacity_logit"][idx][order])
    colour = torch.sigmoid(params["rgb_logit"][idx][order])

    ys, xs = torch.meshgrid(torch.arange(h, device=z.device, dtype=torch.float32) + 0.5,
                            torch.arange(w, device=z.device, dtype=torch.float32) + 0.5, indexing="ij")
    px = xs.reshape(-1)
    py = ys.reshape(-1)

    def shade(px_c, py_c, mu_x, mu_y, ia, ib, id_, op, col):
        dx = px_c[:, None] - mu_x[None, :]
        dy = py_c[:, None] - mu_y[None, :]
        power = -0.5 * (ia * dx * dx + 2 * ib * dx * dy + id_ * dy * dy)
        alpha = (op[None, :] * torch.exp(power.clamp(max=0))).clamp(max=0.99)
        alpha = torch.where(alpha < 1.0 / 255.0, torch.zeros_like(alpha), alpha)
        trans = torch.cumprod(1 - alpha + 1e-10, dim=1)
        trans = torch.cat([torch.ones_like(trans[:, :1]), trans[:, :-1]], 1)
        return (alpha * trans) @ col

    out = []
    for s in range(0, px.shape[0], chunk):
        args = (px[s:s + chunk], py[s:s + chunk], mu_x, mu_y, inv_a, inv_b, inv_d, opacity, colour)
        if torch.is_grad_enabled():
            out.append(checkpoint(shade, *args, use_reentrant=False))
        else:
            out.append(shade(*args))
    return torch.cat(out, 0).reshape(h, w, 3)


def _ssim(a, b):
    torch = _torch()
    import torch.nn.functional as F
    a = a.permute(2, 0, 1)[None]
    b = b.permute(2, 0, 1)[None]
    mu_a, mu_b = F.avg_pool2d(a, 7, 1, 3), F.avg_pool2d(b, 7, 1, 3)
    va = F.avg_pool2d(a * a, 7, 1, 3) - mu_a ** 2
    vb = F.avg_pool2d(b * b, 7, 1, 3) - mu_b ** 2
    cab = F.avg_pool2d(a * b, 7, 1, 3) - mu_a * mu_b
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    return (((2 * mu_a * mu_b + c1) * (2 * cab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (va + vb + c2))).mean()


def _psnr(a, b):
    torch = _torch()
    mse = torch.mean((a - b) ** 2).clamp_min(1e-10)
    return float(-10 * torch.log10(mse))


# ----------------------------------------------------------------------------------------------------------------------
# views
# ----------------------------------------------------------------------------------------------------------------------
def load_views(recon, frames_dir: Path, max_side):
    views = []
    for fr in sorted(recon["frames"], key=lambda f: f["frame_index"]):
        info = recon["images"].get(fr["name"])
        if not fr["registered"] or info is None:
            continue
        img = cv2.imread(str(frames_dir / fr["name"]))
        if img is None:
            continue
        cam = recon["cameras"][str(info["camera_id"])]
        s = min(1.0, max_side / max(img.shape[:2]))
        w, h = int(round(img.shape[1] * s)), int(round(img.shape[0] * s))
        small = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        sx, sy = w / cam["w"], h / cam["h"]
        views.append({"name": fr["name"], "R": np.array(info["axes"], np.float32), "centre": np.array(info["center"], np.float32),
                      "fx": cam["fx"] * sx, "fy": cam["fy"] * sy, "cx": cam["cx"] * sx, "cy": cam["cy"] * sy, "w": w, "h": h,
                      "image": cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0})
    return views


def _to_device(view, device):
    torch = _torch()
    t = lambda x: torch.tensor(x, dtype=torch.float32, device=device)  # noqa: E731
    return {"R": t(view["R"]), "centre": t(view["centre"]), "fx": view["fx"], "fy": view["fy"], "cx": view["cx"], "cy": view["cy"],
            "w": view["w"], "h": view["h"], "image": t(view["image"])}


# ----------------------------------------------------------------------------------------------------------------------
# training
# ----------------------------------------------------------------------------------------------------------------------
def train(gaussians: Gaussians, views, iterations, time_budget, device, ctx=None, seed=0):
    """
    Photometric optimisation of all Gaussian parameters with Adam. Every 8th view is held out to measure generalisation.
    Returns (trained Gaussians, stats). Stops early at the time budget and says how many iterations really ran.
    """
    torch = _torch()
    ctx = ctx or __import__("app.jobs", fromlist=["get"]).get(None)
    rng = np.random.default_rng(seed)
    held = {i for i in range(len(views)) if i % 8 == 7} if len(views) >= 12 else set()
    train_ids = [i for i in range(len(views)) if i not in held]
    dviews = [_to_device(v, device) for v in views]

    def logit(x):
        x = torch.clamp(torch.tensor(x, dtype=torch.float32, device=device), 0.02, 0.98)
        return torch.log(x / (1 - x))

    params = {
        "xyz": torch.tensor(gaussians.xyz, device=device, requires_grad=True),
        "log_scale": torch.tensor(gaussians.log_scale, device=device, requires_grad=True),
        "quat": torch.tensor(gaussians.quat, device=device, requires_grad=True),
        "opacity_logit": torch.tensor(gaussians.opacity_logit, device=device, requires_grad=True),
        "rgb_logit": logit(gaussians.rgb).requires_grad_(True),
    }
    extent = float(np.linalg.norm(gaussians.xyz.max(0) - gaussians.xyz.min(0))) or 1.0
    opt = torch.optim.Adam([
        {"params": [params["xyz"]], "lr": 0.002 * extent},
        {"params": [params["log_scale"]], "lr": 0.02},
        {"params": [params["quat"]], "lr": 0.005},
        {"params": [params["opacity_logit"]], "lr": 0.05},
        {"params": [params["rgb_logit"]], "lr": 0.06},
    ])
    sched = torch.optim.lr_scheduler.ExponentialLR(opt, gamma=0.01 ** (1.0 / max(iterations, 1)))

    def evaluate(ids):
        if not ids:
            return None
        with torch.no_grad():
            return float(np.mean([_psnr(render(params, dviews[i]), dviews[i]["image"]) for i in ids]))

    probe = train_ids[::max(1, len(train_ids) // 4)][:4]
    stats = {"views_total": len(views), "views_train": len(train_ids), "views_heldout": len(held), "gaussians": len(gaussians),
             "device": str(device), "psnr_train_before": evaluate(probe), "psnr_heldout_before": evaluate(sorted(held))}
    t0 = time.time()
    done = 0
    for it in range(iterations):
        if ctx:
            ctx.check()
        if time.time() - t0 > time_budget:
            ctx.log(f"Time budget of {time_budget}s reached after {done} iterations")
            break
        v = dviews[train_ids[rng.integers(len(train_ids))]]
        pred = render(params, v)
        loss = 0.8 * (pred - v["image"]).abs().mean() + 0.2 * (1 - _ssim(pred, v["image"]))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        sched.step()
        done += 1
        if done % 10 == 0:
            ctx.update(progress=88 + 8 * done / iterations, message=f"Gaussian training {done}/{iterations}, loss {loss.item():.4f}" if done % 50 == 0 else None)
    stats.update({"iterations_run": done, "iterations_requested": iterations, "train_seconds": round(time.time() - t0, 1),
                  "psnr_train_after": evaluate(probe), "psnr_heldout_after": evaluate(sorted(held))})
    with torch.no_grad():
        op = torch.sigmoid(params["opacity_logit"])
        keep = (op > 0.02).cpu().numpy()
        out = Gaussians(params["xyz"].detach().cpu().numpy(), params["log_scale"].detach().cpu().numpy(),
                        params["quat"].detach().cpu().numpy(), params["opacity_logit"].detach().cpu().numpy(),
                        torch.sigmoid(params["rgb_logit"]).detach().cpu().numpy())
    stats["pruned_low_opacity"] = int((~keep).sum())
    return out.subset(keep), stats


def cpu_smoke_test():
    """Run one gradient step through the project's differentiable Gaussian rasteriser on CPU."""
    _torch()
    gaussian = Gaussians(
        [[0.0, 0.0, 2.0]],
        [[0.4, 0.4, 0.4]],
        [[1.0, 0.0, 0.0, 0.0]],
        [0.0],
        [[0.8, 0.2, 0.1]],
    )
    view = {
        "R": np.eye(3, dtype=np.float32),
        "centre": np.zeros(3, dtype=np.float32),
        "fx": 12.0,
        "fy": 12.0,
        "cx": 8.0,
        "cy": 8.0,
        "w": 16,
        "h": 16,
        "image": np.full((16, 16, 3), 0.05, dtype=np.float32),
    }
    _, stats = train(gaussian, [view], iterations=1, time_budget=5, device="cpu")
    return stats["iterations_run"] == 1 and np.isfinite(stats["psnr_train_after"])


def render_numpy(g: Gaussians, view, device="cpu"):
    """Render a Gaussian set from one view with the built-in rasteriser. Returns uint8 RGB."""
    torch = _torch()
    p = {"xyz": torch.tensor(g.xyz, device=device), "log_scale": torch.tensor(g.log_scale, device=device),
         "quat": torch.tensor(g.quat, device=device), "opacity_logit": torch.tensor(g.opacity_logit, device=device)}
    x = torch.clamp(torch.tensor(g.rgb, device=device), 0.02, 0.98)
    p["rgb_logit"] = torch.log(x / (1 - x))
    with torch.no_grad():
        img = render(p, _to_device(view, device))
    return (img.clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)


# ----------------------------------------------------------------------------------------------------------------------
# file formats
# ----------------------------------------------------------------------------------------------------------------------
def _ply_properties():
    return (["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
             "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"])


def write_gaussian_ply(path: Path, g: Gaussians):
    """Standard 3DGS PLY (what the reference implementation, Open3D, SuperSplat and most viewers read): SH degree 0."""
    n = len(g)
    data = np.zeros((n, 17), np.float32)
    data[:, 0:3] = g.xyz
    data[:, 6:9] = (g.rgb - 0.5) / SH_C0
    data[:, 9] = g.opacity_logit
    data[:, 10:13] = g.log_scale
    data[:, 13:17] = g.quat
    header = "ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n" + "".join(f"property float {p}\n" for p in _ply_properties()) + "end_header\n"
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(data.tobytes())


def read_gaussian_ply(path: Path) -> Gaussians:
    raw = Path(path).read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    head = raw[:end].decode("ascii").splitlines()
    n = int(next(l for l in head if l.startswith("element vertex")).split()[-1])
    props = [l.split()[-1] for l in head if l.startswith("property")]
    data = np.frombuffer(raw[end:], np.float32, count=n * len(props)).reshape(n, len(props))
    col = lambda name: data[:, props.index(name)]  # noqa: E731
    xyz = np.stack([col("x"), col("y"), col("z")], 1)
    rgb = np.stack([col(f"f_dc_{i}") for i in range(3)], 1) * SH_C0 + 0.5
    scale = np.stack([col(f"scale_{i}") for i in range(3)], 1)
    quat = np.stack([col(f"rot_{i}") for i in range(4)], 1)
    return Gaussians(xyz, scale, quat, col("opacity"), rgb)


def write_splat(path: Path, g: Gaussians):
    """The compact .splat format (32 bytes per Gaussian), sorted largest and most opaque first as web viewers expect."""
    order = np.argsort(-(np.exp(g.log_scale).sum(1) * (1 / (1 + np.exp(-g.opacity_logit)))))
    n = len(g)
    buf = np.zeros(n, dtype=[("pos", "<f4", 3), ("scale", "<f4", 3), ("rgba", "u1", 4), ("rot", "u1", 4)])
    buf["pos"] = g.xyz[order]
    buf["scale"] = np.exp(g.log_scale[order])
    alpha = 1 / (1 + np.exp(-g.opacity_logit[order]))
    buf["rgba"][:, :3] = np.clip(g.rgb[order] * 255, 0, 255).round()
    buf["rgba"][:, 3] = np.clip(alpha * 255, 0, 255).round()
    buf["rot"] = np.clip(g.quat[order] * 128 + 128, 0, 255).round()
    Path(path).write_bytes(buf.tobytes())


def read_splat(path: Path) -> Gaussians:
    buf = np.frombuffer(Path(path).read_bytes(), dtype=[("pos", "<f4", 3), ("scale", "<f4", 3), ("rgba", "u1", 4), ("rot", "u1", 4)])
    alpha = np.clip(buf["rgba"][:, 3] / 255.0, 1e-4, 1 - 1e-4)
    return Gaussians(buf["pos"], np.log(np.maximum(buf["scale"], 1e-9)), (buf["rot"].astype(np.float32) - 128) / 128,
                     np.log(alpha / (1 - alpha)), buf["rgba"][:, :3] / 255.0)


SPZ_MAGIC, SPZ_VERSION, SPZ_FRACTIONAL_BITS = 0x5053474E, 2, 12


def write_spz(path: Path, g: Gaussians):
    """
    Niantic SPZ (gzip-compressed, version 2, SH degree 0), written from the published layout: 16-byte header, then
    24-bit fixed-point positions, alphas, colours, log-scales and 3-byte rotations. Validate it in your own viewer before
    relying on it: this writer has been round-trip tested with the reader below but not against Niantic's reference loader.
    """
    n = len(g)
    header = struct.pack("<IIIBBBB", SPZ_MAGIC, SPZ_VERSION, n, 0, SPZ_FRACTIONAL_BITS, 0, 0)
    fixed = np.round(g.xyz.astype(np.float64) * (1 << SPZ_FRACTIONAL_BITS)).astype(np.int64)
    fixed = np.clip(fixed, -(1 << 23), (1 << 23) - 1) & 0xFFFFFF
    pos = np.stack([fixed & 0xFF, (fixed >> 8) & 0xFF, (fixed >> 16) & 0xFF], axis=2).astype(np.uint8)  # (n, 3 coords, 3 bytes)
    alpha = np.clip(1 / (1 + np.exp(-g.opacity_logit)) * 255, 0, 255).round().astype(np.uint8)
    f_dc = (g.rgb - 0.5) / SH_C0
    colour = np.clip((f_dc * 0.15 + 0.5) * 255, 0, 255).round().astype(np.uint8)
    scale = np.clip((g.log_scale + 10) * 16, 0, 255).round().astype(np.uint8)
    q = g.quat.copy()
    q[q[:, 0] < 0] *= -1  # the stored w is implied to be non-negative
    rot = np.clip(q[:, 1:4] * 127.5 + 127.5, 0, 255).round().astype(np.uint8)
    body = pos.tobytes() + alpha.tobytes() + colour.tobytes() + scale.tobytes() + rot.tobytes()
    with gzip.open(path, "wb") as f:
        f.write(header + body)


def read_spz(path: Path) -> Gaussians:
    raw = gzip.open(path, "rb").read()
    magic, version, n, sh, bits, _, _ = struct.unpack("<IIIBBBB", raw[:16])
    if magic != SPZ_MAGIC or version != 2 or sh != 0:
        raise ValueError("unsupported SPZ file")
    o = 16
    pos = np.frombuffer(raw, np.uint8, n * 9, o).reshape(n, 3, 3).astype(np.int64)
    o += n * 9
    fixed = pos[:, :, 0] | (pos[:, :, 1] << 8) | (pos[:, :, 2] << 16)
    fixed = np.where(fixed & 0x800000, fixed - (1 << 24), fixed)
    xyz = fixed.astype(np.float32) / (1 << bits)
    alpha = np.frombuffer(raw, np.uint8, n, o).astype(np.float32) / 255
    o += n
    colour = np.frombuffer(raw, np.uint8, n * 3, o).reshape(n, 3).astype(np.float32)
    o += n * 3
    scale = np.frombuffer(raw, np.uint8, n * 3, o).reshape(n, 3).astype(np.float32) / 16 - 10
    o += n * 3
    r = (np.frombuffer(raw, np.uint8, n * 3, o).reshape(n, 3).astype(np.float32) - 127.5) / 127.5
    w = np.sqrt(np.clip(1 - (r ** 2).sum(1), 0, 1))
    alpha = np.clip(alpha, 1e-4, 1 - 1e-4)
    rgb = ((colour / 255 - 0.5) / 0.15) * SH_C0 + 0.5
    return Gaussians(xyz, scale, np.concatenate([w[:, None], r], 1), np.log(alpha / (1 - alpha)), rgb)


# ----------------------------------------------------------------------------------------------------------------------
# Open3D rendering of the exported splat file
# ----------------------------------------------------------------------------------------------------------------------
def render_with_open3d(ply_path: Path, out_png: Path, view, width=640, height=480):
    """
    Open3D 0.20 Gaussian splat renderer. It needs Vulkan (Linux/Windows) or Metal and an offscreen-capable driver, so this
    is attempted in a child process with a timeout and reports failure instead of crashing the service.
    Returns (ok, message).
    """
    import subprocess
    import sys
    script = r'''
import sys, json, numpy as np
import open3d as o3d
import open3d.visualization.rendering as rendering
ply, out, w, h, cfg = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), json.loads(sys.argv[5])
pcd = o3d.t.io.read_point_cloud(ply)
mat = rendering.MaterialRecord()
mat.shader = "gaussianSplat"
r = rendering.OffscreenRenderer(w, h)
r.scene.add_geometry("splat", pcd, mat)
K = np.array(cfg["K"], dtype=np.float64)
extr = np.array(cfg["extrinsic"], dtype=np.float64)
r.setup_camera(o3d.camera.PinholeCameraIntrinsic(w, h, K[0, 0], K[1, 1], K[0, 2], K[1, 2]), extr)
img = r.render_to_image()
o3d.io.write_image(out, img)
print("rendered")
'''
    s = min(width / view["w"], height / view["h"])
    K = [[view["fx"] * s, 0, view["cx"] * s], [0, view["fy"] * s, view["cy"] * s], [0, 0, 1]]
    T = np.eye(4)
    T[:3, :3] = view["R"]
    T[:3, 3] = -np.asarray(view["R"]) @ np.asarray(view["centre"])
    cfg = {"K": K, "extrinsic": T.tolist()}
    try:
        p = subprocess.run([sys.executable, "-c", script, str(ply_path), str(out_png), str(int(view["w"] * s)), str(int(view["h"] * s)), json.dumps(cfg)],
                           capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return False, "Open3D offscreen renderer did not finish in 90 s (no usable Vulkan/GPU context?)"
    if p.returncode != 0 or not Path(out_png).exists():
        return False, "Open3D could not render the splat: " + ((p.stderr or p.stdout or "no output")[-240:]).strip()
    return True, "rendered by Open3D"


# ----------------------------------------------------------------------------------------------------------------------
# stage entry point
# ----------------------------------------------------------------------------------------------------------------------
def run_stage(work_rel: str, frames_rel: str, ctx):
    work = config.resolve(work_rel)
    frames_dir = config.resolve(frames_rel)
    out_dir = work / "outputs"
    out_dir.mkdir(exist_ok=True)

    def fail(status, msg, **kw):
        report.stage(work, "gaussian_splat", status, msg, **kw)
        ctx.log("Gaussian splat: " + msg)
        return {"status": status, "message": msg}

    if not config.SPLAT_ENABLED:
        return fail("skipped", "SPLAT_ENABLED=0")
    recon = json.loads((work / "reconstruction.json").read_text())
    if recon["is_360"]:
        return fail("unavailable", "Gaussian training uses the flat frames; 360° footage is not supported by this trainer")
    try:
        torch = _torch()
    except PipelineError as e:
        return fail("unavailable", str(e))

    views = load_views(recon, frames_dir, config.SPLAT_MAX_SIDE)
    if len(views) < config.SPLAT_MIN_VIEWS:
        return fail("failed", f"Only {len(views)} registered views are available; at least {config.SPLAT_MIN_VIEWS} are needed to train")

    mesh_cloud = out_dir / "pointcloud_dense.ply"
    source = "sparse SfM points"
    pts_data = np.load(work / "points_full.npz")
    points, colours = pts_data["positions"], pts_data["colors"]
    if mesh_cloud.exists():
        try:
            import open3d as o3d
            pc = o3d.io.read_point_cloud(str(mesh_cloud))
            if len(pc.points) >= 200:
                points, colours = np.asarray(pc.points), (np.asarray(pc.colors) * 255).astype(np.uint8)
                source = "dense TSDF surface points"
        except Exception as e:
            ctx.log(f"Dense points not used: {e}")
    if len(points) < 100:
        return fail("failed", f"Only {len(points)} points are available to initialise Gaussians")

    free = hardware.available_ram_mb()
    n_max = config.SPLAT_MAX_GAUSSIANS if free is None or free > config.MEMORY_RESERVE_MB + 1500 else min(config.SPLAT_MAX_GAUSSIANS, 2000)
    g0 = initial_gaussians(points, colours, n_max)
    ctx.update("splat", 88, f"Training {len(g0)} Gaussians from {source} on {len(views)} views")

    want = hardware.select_devices()["torch_device"]
    tried = [want] if want == "cpu" else [want, "cpu"]
    result, device_used, errors = None, None, []
    for dev in tried:
        try:
            result = train(g0, views, config.SPLAT_ITERATIONS, config.SPLAT_TIME_BUDGET_SEC, torch.device(dev), ctx)
            device_used = dev
            break
        except Cancelled:
            raise
        except Exception as e:  # e.g. an op missing on XPU: retry on the CPU, and say so
            errors.append(f"{dev}: {str(e)[:160]}")
            ctx.log(f"Gaussian training failed on {dev}: {e}")
    if result is None:
        return fail("failed", "Gaussian training failed: " + "; ".join(errors))
    g, stats = result
    if len(g) < 50:
        return fail("failed", "Training pruned almost every Gaussian; no model was written", stats=stats)

    ply, splat, spz = out_dir / "gaussians.ply", out_dir / "gaussians.splat", out_dir / "gaussians.spz"
    write_gaussian_ply(ply, g)
    write_splat(splat, g)
    write_spz(spz, g)
    for p, key, kind, label in ((ply, "gaussian_ply", "gaussian-ply", "Gaussian splat (PLY)"),
                                (splat, "gaussian_splat", "splat", "Gaussian splat (.splat)"),
                                (spz, "gaussian_spz", "spz", "Gaussian splat (SPZ, experimental)")):
        report.output(work, key, f"{work_rel}/outputs/{p.name}", kind, p.stat().st_size, label, gaussians=len(g))

    # preview renders of a training view and a held-out-style comparison, drawn by the built-in rasteriser
    mid = views[len(views) // 2]
    ref_bgr = cv2.cvtColor((mid["image"] * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    mine = cv2.cvtColor(render_numpy(g, mid, device_used), cv2.COLOR_RGB2BGR)
    side_by_side = np.hstack([ref_bgr, mine])
    cv2.putText(side_by_side, "video frame", (6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(side_by_side, "Gaussians", (ref_bgr.shape[1] + 6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    cmp_png = out_dir / "splat_preview.png"
    cv2.imwrite(str(cmp_png), cv2.resize(side_by_side, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
    report.output(work, "splat_preview", f"{work_rel}/outputs/{cmp_png.name}", "png", cmp_png.stat().st_size,
                  "Frame vs. Gaussian render (built-in rasteriser)", renderer="builtin-torch-rasteriser")

    msg = "Disabled in CPU-only mode; using the built-in CPU rasteriser"
    render_status = {"open3d": {"ok": False, "message": msg}, "builtin": {"ok": True}}

    gain = None if stats["psnr_train_before"] is None else round(stats["psnr_train_after"] - stats["psnr_train_before"], 2)
    report.stage(work, "gaussian_splat", "ok",
                 f"{len(g)} Gaussians trained for {stats['iterations_run']} iterations on {device_used.upper()} (PSNR {gain:+} dB on training views)"
                 if gain is not None else f"{len(g)} Gaussians trained",
                 device_used=device_used, initialised_from=source, stats=stats, rendering=render_status,
                 formats=["ply", "splat", "spz (experimental)"],
                 note="Low-resolution CPU trainer without adaptive densification: a compact preview-quality model, not a "
                      "CUDA-class 3DGS result.")
    hardware.record_runtime_success("gaussian_splatting")
    ctx.log(f"Gaussians written: {len(g)} ({device_used}); Open3D renderer: {msg}")
    return {"status": "ok", "device": device_used, "gaussians": len(g)}
