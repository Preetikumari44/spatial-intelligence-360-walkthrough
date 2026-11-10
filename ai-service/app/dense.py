"""
Open3D geometry stages: sparse point cloud (PLY), and a TSDF-fused mesh (PLY/OBJ) from per-frame depth.

Depth comes from a pluggable provider. The production provider is a monocular depth network whose output is fitted to the
SfM points of each frame (scale and shift), so the fused surface is consistent with the recovered camera poses but only
as accurate as monocular depth is. If no provider is available the mesh stage reports "unavailable" instead of faking one.
All Open3D tensor operations run on CPU; CUDA, SYCL and XPU are not used.
"""
import json
import logging
from pathlib import Path

import cv2
import numpy as np

from . import config, hardware, report
from .errors import PipelineError

log = logging.getLogger("dense")


# ----------------------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------------------
def _o3d():
    try:
        import open3d as o3d
        import open3d.core as o3c
        return o3d, o3c
    except ImportError as e:
        raise PipelineError("The standard CPU Open3D package is not installed (run scripts\\setup-ai.ps1).", 503) from e


def cpu_smoke_test():
    """Run a small real CPU TSDF integration to verify dense geometry operations, not just Open3D import."""
    o3d, o3c = _o3d()
    device = o3c.Device("CPU:0")
    height, width = 32, 32
    depth = np.full((height, width), 2.0, dtype=np.float32)
    color = np.full((height, width, 3), 0.5, dtype=np.float32)
    intrinsics = o3c.Tensor(np.array([[28.0, 0.0, 15.5], [0.0, 28.0, 15.5], [0.0, 0.0, 1.0]]), o3c.float64)
    extrinsics = o3c.Tensor(np.eye(4), o3c.float64)
    depth_image = o3d.t.geometry.Image(o3c.Tensor(depth, device=device))
    color_image = o3d.t.geometry.Image(o3c.Tensor(color, device=device))
    volume = o3d.t.geometry.VoxelBlockGrid(
        attr_names=("tsdf", "weight", "color"),
        attr_dtypes=(o3c.float32, o3c.float32, o3c.float32),
        attr_channels=(1, 1, 3),
        voxel_size=0.1,
        block_resolution=8,
        block_count=128,
        device=device,
    )
    blocks = volume.compute_unique_block_coordinates(depth_image, intrinsics, extrinsics, 1.0, 3.0, 4.0)
    volume.integrate(blocks, depth_image, color_image, intrinsics, extrinsics, 1.0, 3.0, 4.0)
    mesh = volume.extract_triangle_mesh(weight_threshold=0.0)
    return int(mesh.triangle.indices.shape[0]) > 0


def _with_fallback(label, device, fn, ctx):
    """Run fn(device) on the preferred device; on any failure log it and rerun on the CPU. Returns (result, device_used)."""
    if device != "CPU:0":
        try:
            return fn(device), device
        except Exception as e:  # SYCL kernels can be missing for an op; never let that kill the job
            ctx.log(f"{label}: {device} failed ({str(e)[:160]}); falling back to CPU:0")
    return fn("CPU:0"), "CPU:0"


def _file_entry(work, work_rel, key, path: Path, kind, label, **extra):
    rel = f"{work_rel}/outputs/{path.name}"
    report.output(work, key, rel, kind, path.stat().st_size, label, **extra)


def _recon(work: Path):
    return json.loads((work / "reconstruction.json").read_text())


# ----------------------------------------------------------------------------------------------------------------------
# point cloud
# ----------------------------------------------------------------------------------------------------------------------
def build_pointcloud(work_rel: str, ctx):
    o3d, o3c = _o3d()
    work = config.resolve(work_rel)
    out_dir = work / "outputs"
    out_dir.mkdir(exist_ok=True)
    data = np.load(work / "points_full.npz")
    pos, col = data["positions"], data["colors"]
    if len(pos) < 30:
        report.stage(work, "point_cloud", "failed", f"Only {len(pos)} reconstructed points; too few for a point cloud")
        return {"status": "failed"}
    dev = hardware.select_devices()["open3d_device"]

    def work_fn(device):
        d = o3c.Device(device)
        pcd = o3d.t.geometry.PointCloud(d)
        pcd.point.positions = o3c.Tensor(pos.astype(np.float32), device=d)
        pcd.point.colors = o3c.Tensor(col.astype(np.float32) / 255.0, device=d)
        extent = float(np.linalg.norm(np.percentile(pos, 99, 0) - np.percentile(pos, 1, 0)))
        pcd.estimate_normals(max_nn=30, radius=extent * 0.05)
        return pcd.to(o3c.Device("CPU:0"))

    pcd, used = _with_fallback("normals", dev, work_fn, ctx)
    legacy = pcd.to_legacy()
    n_before = len(legacy.points)
    legacy, _ = legacy.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.5)  # CPU only: no tensor equivalent used here
    path = out_dir / "pointcloud.ply"
    if not o3d.io.write_point_cloud(str(path), legacy, write_ascii=False):
        raise PipelineError("Open3D could not write the point cloud", 500)
    _file_entry(work, work_rel, "pointcloud", path, "ply", "Sparse point cloud (PLY)", points=len(legacy.points))
    report.stage(work, "point_cloud", "ok", f"{len(legacy.points)} points after removing {n_before - len(legacy.points)} outliers",
                 device_used=used, points=len(legacy.points), kind="sparse SfM points")
    ctx.log(f"Point cloud written: {len(legacy.points)} points (normals on {used})")
    return {"status": "ok", "device": used, "points": len(legacy.points)}


# ----------------------------------------------------------------------------------------------------------------------
# depth providers
# ----------------------------------------------------------------------------------------------------------------------
class MonoDepthProvider:
    """Monocular depth network (default: Depth Anything V2 metric indoor) via transformers. Needs the model files once."""
    name = "monocular-depth"

    def __init__(self, torch_device="cpu"):
        from transformers import pipeline
        self.pipe = None
        errors = []
        for dev in ([torch_device, "cpu"] if torch_device != "cpu" else ["cpu"]):
            try:
                self.pipe = pipeline("depth-estimation", model=config.DEPTH_MODEL, device=dev)
                self.device = dev
                break
            except Exception as e:
                errors.append(f"{dev}: {e}")
        if self.pipe is None:
            raise RuntimeError("; ".join(errors)[:300])

    def depth(self, bgr, name):
        from PIL import Image
        out = self.pipe(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
        d = out["predicted_depth"].squeeze().float().cpu().numpy()
        return cv2.resize(d, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_LINEAR)


def default_provider():
    """Returns (provider, None) or (None, reason)."""
    if not config.DEPTH_ENABLED:
        return None, "DEPTH_ENABLED=0"
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
    except ImportError as e:
        return None, f"transformers/PyTorch missing: {e}"
    try:
        return MonoDepthProvider(hardware.select_devices()["torch_device"]), None
    except Exception as e:
        return None, f"depth model could not be loaded (first run needs internet to download it): {e}"


def align_depth(raw, uv, z_sfm, rng=None):
    """
    Fit z_sfm ~ s * raw + b with a small RANSAC and return (s, b, inlier_ratio) or None.
    raw: depth predicted at the sparse points' pixels; z_sfm: their depth in the SfM frame.
    """
    rng = rng or np.random.default_rng(0)
    n = len(raw)
    if n < 25:
        return None
    best, best_in = None, 0
    tol = np.maximum(0.06 * z_sfm, 1e-6)
    for _ in range(200):
        i, j = rng.choice(n, 2, replace=False)
        if abs(raw[i] - raw[j]) < 1e-6:
            continue
        s = (z_sfm[i] - z_sfm[j]) / (raw[i] - raw[j])
        b = z_sfm[i] - s * raw[i]
        if s <= 0:
            continue
        inl = np.abs(s * raw + b - z_sfm) < tol
        if inl.sum() > best_in:
            best, best_in = inl, int(inl.sum())
    if best is None or best_in < 20 or best_in / n < 0.4:
        return None
    A = np.stack([raw[best], np.ones(best_in)], 1)
    s, b = np.linalg.lstsq(A, z_sfm[best], rcond=None)[0]
    if s <= 0:
        return None
    return float(s), float(b), best_in / n


# ----------------------------------------------------------------------------------------------------------------------
# ICP (optional refinement, off by default)
# ----------------------------------------------------------------------------------------------------------------------
def icp_refine(source_xyz, target_xyz, max_distance, device="CPU:0", init=None):
    """Point-to-point ICP with Open3D's tensor pipeline. Returns (4x4 source->target, fitness, rmse)."""
    o3d, o3c = _o3d()
    d = o3c.Device(device)
    src = o3d.t.geometry.PointCloud(o3c.Tensor(np.asarray(source_xyz, np.float32), device=d))
    tgt = o3d.t.geometry.PointCloud(o3c.Tensor(np.asarray(target_xyz, np.float32), device=d))
    init_t = o3c.Tensor(np.eye(4) if init is None else init, o3c.float64)  # kept on the CPU, as Open3D expects
    res = o3d.t.pipelines.registration.icp(src, tgt, max_distance, init_t,
                                           o3d.t.pipelines.registration.TransformationEstimationPointToPoint(),
                                           o3d.t.pipelines.registration.ICPConvergenceCriteria(max_iteration=40))
    return res.transformation.cpu().numpy(), float(res.fitness), float(res.inlier_rmse)


# ----------------------------------------------------------------------------------------------------------------------
# TSDF mesh
# ----------------------------------------------------------------------------------------------------------------------
def _frames_for_fusion(recon, frames_dir: Path, limit):
    names = [f["name"] for f in sorted(recon["frames"], key=lambda f: f["frame_index"]) if f["registered"] and f["name"] in recon["images"]]
    if len(names) > limit:
        names = [names[i] for i in sorted(set(np.linspace(0, len(names) - 1, limit).round().astype(int).tolist()))]
    return names


def build_mesh(work_rel: str, frames_rel: str, ctx, provider=None):
    o3d, o3c = _o3d()
    work = config.resolve(work_rel)
    frames_dir = config.resolve(frames_rel)
    out_dir = work / "outputs"
    out_dir.mkdir(exist_ok=True)
    recon = _recon(work)
    if recon["is_360"]:
        report.stage(work, "mesh", "unavailable", "Mesh fusion is implemented for flat video only; 360° footage keeps the point cloud and tour")
        return {"status": "unavailable"}

    reason = None
    if provider is None:
        provider, reason = default_provider()
    if provider is None:
        report.stage(work, "mesh", "unavailable", f"No depth source for mesh fusion: {reason}. The point cloud and tour are unaffected.")
        ctx.log(f"Mesh skipped: {reason}")
        return {"status": "unavailable", "reason": reason}

    pts = np.load(work / "points_full.npz")["positions"].astype(np.float64)
    names = _frames_for_fusion(recon, frames_dir, config.DENSE_MAX_FRAMES)
    ext = recon["extents"]
    diag = float(np.sqrt(ext["x"] ** 2 + ext["y"] ** 2 + ext["z"] ** 2))
    voxel = max(ext["x"], ext["y"], ext["z"]) / config.DENSE_VOXELS
    dev_pref = hardware.select_devices()["open3d_device"]
    ctx.update("dense", 72, f"Estimating depth for {len(names)} frames with {provider.name}")

    prepared = []  # (extrinsic, K, depth, rgb) per usable frame
    skipped = 0
    for n, name in enumerate(names):
        ctx.check()
        info = recon["images"][name]
        cam = recon["cameras"][str(info["camera_id"])]
        bgr = cv2.imread(str(frames_dir / name))
        if bgr is None:
            skipped += 1
            continue
        s = min(1.0, config.DENSE_DEPTH_SIDE / max(bgr.shape[:2]))
        small = cv2.resize(bgr, (int(round(bgr.shape[1] * s)), int(round(bgr.shape[0] * s))), interpolation=cv2.INTER_AREA) if s < 1 else bgr
        h, w = small.shape[:2]
        sx, sy = w / cam["w"], h / cam["h"]
        K = np.array([[cam["fx"] * sx, 0, cam["cx"] * sx], [0, cam["fy"] * sy, cam["cy"] * sy], [0, 0, 1]])
        centre, R = np.array(info["center"]), np.array(info["axes"])
        raw = provider.depth(small, name)
        pc = (pts - centre) @ R.T
        z = pc[:, 2]
        ok = z > 1e-3
        u = K[0, 0] * pc[ok, 0] / z[ok] + K[0, 2]
        v = K[1, 1] * pc[ok, 1] / z[ok] + K[1, 2]
        inside = (u >= 0) & (u < w - 1) & (v >= 0) & (v < h - 1)
        ui, vi, zi = u[inside].astype(int), v[inside].astype(int), z[ok][inside]
        fit = align_depth(raw[vi, ui].astype(np.float64), None, zi)
        if fit is None:
            skipped += 1
            ctx.log(f"Frame {name}: depth could not be aligned to the SfM points; frame skipped")
            continue
        scale, shift, ratio = fit
        depth = (scale * raw + shift).astype(np.float32)
        depth[(depth < 0.05 * diag * 0.01) | (depth > 2.0 * diag)] = 0.0
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = -R @ centre
        prepared.append((T, K, depth, cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
        ctx.update(progress=72 + 12 * (n + 1) / len(names), message=f"Depth {n + 1}/{len(names)} aligned (scale {scale:.3f}, {ratio:.0%} inliers)" if n % 5 == 0 else None)

    if len(prepared) < 4:
        report.stage(work, "mesh", "failed", f"Depth could be aligned to the reconstruction for only {len(prepared)} frames", skipped_frames=skipped)
        return {"status": "failed"}

    ctx.update("dense", 85, f"Fusing {len(prepared)} depth maps into a TSDF volume")
    # the voxel hash map is allocated up front (512 voxels x 20 bytes per block); budget 15% of free RAM, 150-600 MB.
    # Integrated graphics share this memory, so the same budget applies on SYCL.
    free = hardware.available_ram_mb() or 4000
    budget_bytes = min(max(0.15 * free, 150), 600) * 1048576
    block_count = int(budget_bytes / (512 * 20))

    def fuse(device):
        d = o3c.Device(device)
        vbg = o3d.t.geometry.VoxelBlockGrid(attr_names=("tsdf", "weight", "color"),
                                            attr_dtypes=(o3c.float32, o3c.float32, o3c.float32),
                                            attr_channels=(1, 1, 3), voxel_size=voxel, block_resolution=8,
                                            block_count=block_count, device=d)
        for T, K, depth, rgb in prepared:
            ctx.check()
            depth_img = o3d.t.geometry.Image(o3c.Tensor(depth, device=d))
            color_img = o3d.t.geometry.Image(o3c.Tensor(rgb.astype(np.float32) / 255.0, device=d))
            intr = o3c.Tensor(K, o3c.float64)
            extr = o3c.Tensor(T, o3c.float64)
            coords = vbg.compute_unique_block_coordinates(depth_img, intr, extr, 1.0, 1.5 * diag, 4.0)
            vbg.integrate(coords, depth_img, color_img, intr, extr, 1.0, 1.5 * diag, 4.0)
        mesh = vbg.extract_triangle_mesh(weight_threshold=2.0)
        cloud = vbg.extract_point_cloud(weight_threshold=2.0)
        return mesh.to(o3c.Device("CPU:0")).to_legacy(), cloud.to(o3c.Device("CPU:0")).to_legacy()

    (mesh, cloud), used = _with_fallback("TSDF fusion", dev_pref, fuse, ctx)
    if len(mesh.triangles) < 50:
        report.stage(work, "mesh", "failed", f"TSDF fusion produced only {len(mesh.triangles)} triangles", device_used=used)
        return {"status": "failed"}

    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_vertices()
    labels, counts, _ = mesh.cluster_connected_triangles()
    labels, counts = np.asarray(labels), np.asarray(counts)
    drop = counts[labels] < max(30, 0.02 * len(mesh.triangles))
    mesh.remove_triangles_by_mask(drop)
    mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()

    ply, obj, dense_ply = out_dir / "mesh.ply", out_dir / "mesh.obj", out_dir / "pointcloud_dense.ply"
    if not o3d.io.write_triangle_mesh(str(ply), mesh):
        raise PipelineError("Open3D could not write mesh.ply", 500)
    o3d.io.write_triangle_mesh(str(obj), mesh)
    if len(cloud.points):
        o3d.io.write_point_cloud(str(dense_ply), cloud)
    for p in (ply, obj):
        if not p.exists() or p.stat().st_size == 0:
            raise PipelineError(f"{p.name} was not written", 500)
    _file_entry(work, work_rel, "mesh_ply", ply, "ply", "Mesh (PLY, vertex colours)", triangles=len(mesh.triangles))
    _file_entry(work, work_rel, "mesh_obj", obj, "obj", "Mesh (OBJ)", triangles=len(mesh.triangles))
    if dense_ply.exists():
        _file_entry(work, work_rel, "pointcloud_dense", dense_ply, "ply", "Dense surface points (PLY)", points=len(cloud.points))
    report.stage(work, "mesh", "ok", f"{len(mesh.triangles)} triangles from {len(prepared)} fused depth maps",
                 device_used=used, depth_source=provider.name, fused_frames=len(prepared), skipped_frames=skipped,
                 voxel_size_model_units=round(voxel, 5),
                 note="Depth is monocular and fitted to the SfM points: shapes are approximate, not survey-grade.")
    hardware.record_runtime_success("dense_mesh")
    ctx.log(f"Mesh written: {len(mesh.triangles)} triangles (TSDF on {used})")
    return {"status": "ok", "device": used, "triangles": len(mesh.triangles)}
