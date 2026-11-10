"""Camera poses and a sparse point cloud: COLMAP when installed, otherwise the built-in OpenCV pipeline (flat video)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import colmap_compat, colmap_locator, colmap_validate, config, geometry, hardware, jobs, memory_plan, report, sfm
from .errors import Cancelled, PipelineError

FACE_YAWS = (0, 90, 180, 270)


class ColmapOOM(PipelineError):
    """A COLMAP stage died from memory exhaustion; the caller may retry once with a smaller plan."""

    def __init__(self, label, tail):
        super().__init__(f"COLMAP {label} ran out of memory: {tail}", 507)


def _run(cmd, label, ctx, log_dir=None):
    """Run one COLMAP command. Complete stdout and stderr are written to <log_dir>/<label>.stdout.log / .stderr.log."""
    env = colmap_locator.env_for(str(cmd[0]))   # bundled bin folder first on PATH so Windows finds COLMAP's DLLs
    ctx.check()
    ctx.log("$ " + " ".join(str(c) for c in cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", env=env)
    ctx.processes.append(proc)
    try:
        out, err = proc.communicate(timeout=config.COLMAP_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        proc.communicate()
        raise PipelineError(f"COLMAP {label} timed out after {config.COLMAP_TIMEOUT}s", 504) from e
    finally:
        if proc in ctx.processes:
            ctx.processes.remove(proc)
    if log_dir is not None:
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            (Path(log_dir) / f"{label}.stdout.log").write_text(out or "", encoding="utf-8", errors="replace")
            (Path(log_dir) / f"{label}.stderr.log").write_text(err or "", encoding="utf-8", errors="replace")
        except OSError:
            pass
    if ctx.cancel_event.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        tail = (err or out or "")[-600:]
        diagnostics = (err or "") + "\n" + (out or "")
        loader = colmap_locator.describe_exit(proc.returncode)
        if loader:
            raise PipelineError(f"COLMAP {label} could not start: {loader}", 503)
        if colmap_compat.looks_like_oom(proc.returncode, diagnostics):
            raise ColmapOOM(label, tail)
        if label == "mapper" and ("No good initial image pair found" in diagnostics
                                  or "Failed to create any sparse model" in diagnostics):
            raise PipelineError(
                "COLMAP could not start a 3D model because no camera pair had enough parallax and overlapping visual detail. "
                "For a 3D walkthrough, record a slow, steady walk with forward or sideways camera movement, textured surfaces, "
                "good light, and overlap between neighboring views. The video-viewpoint tour remains available. A genuine 360 "
                "panorama requires 2:1 equirectangular footage marked as 360° when uploaded.",
                422,
            )
        raise PipelineError(f"COLMAP {label} failed (exit code {proc.returncode}): {tail}", 500)
    return out


def _prepare_images(frames_dir: Path, work: Path, frames, is_360):
    images = work / "images"
    images.mkdir(parents=True)
    if not is_360:
        for f in frames:
            shutil.copy2(frames_dir / f["name"], images / f["name"])  # symlinks need admin rights on Windows
        return images
    for f in frames:
        img = cv2.imread(str(frames_dir / f["name"]))
        if img is None:
            continue
        stem = Path(f["name"]).stem
        for k, yaw in enumerate(FACE_YAWS):
            cv2.imwrite(str(images / f"{stem}__{k}.jpg"), geometry.equirect_to_persp(img, yaw), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return images


def _best_model(work: Path, ctx, caps):
    sparse = work / "sparse"
    best, best_count = None, 0
    counts = []
    for model in sorted(p for p in sparse.iterdir() if p.is_dir()) if sparse.exists() else []:
        txt = work / f"txt_{model.name}"
        txt.mkdir(exist_ok=True)
        _run(colmap_compat.build_model_converter(caps, model, txt), "model_converter", ctx, work / "colmap_logs")
        count = len(geometry.parse_images((txt / "images.txt").read_text()))
        counts.append(count)
        if count > best_count:
            best, best_count = txt, count
    return best, best_count, counts


def _memory_gate(ctx, stage):
    """Checked before each expensive COLMAP stage so a machine that filled up mid-job stops with advice instead of thrashing."""
    free = hardware.available_ram_mb()
    if free is not None and free < config.MIN_FREE_RAM_MB:
        raise PipelineError(f"Only {free} MB of RAM is free before {stage}; at least {config.MIN_FREE_RAM_MB} MB is needed. "
                            "Close other programs and use Retry (the job will pick a smaller plan automatically).", 503)


def _colmap_sfm(colmap, frames_dir, frames, work, is_360, ctx, plan, caps):
    """One COLMAP attempt with the given memory plan. Temporary image copies are always removed."""
    used_frames = memory_plan.subsample(frames, plan.max_images)
    if len(used_frames) < len(frames):
        ctx.log(f"Adaptive sampling: {len(used_frames)} of {len(frames)} frames used ({plan.tier} plan, max {plan.max_images})")
    images = _prepare_images(frames_dir, work, used_frames, is_360)
    try:
        total_images = len(list(images.iterdir()))
        db = work / "database.db"
        sparse = work / "sparse"
        for stale in (db, sparse):  # a retry must not inherit a half-written database or model
            if stale.is_file():
                stale.unlink()
            elif stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
        sparse.mkdir()
        cs = colmap_compat.build_commands(
            caps, db=db, images=images, sparse=sparse, max_image_size=plan.max_side, max_features=plan.max_features,
            threads=plan.threads, n_images=total_images, exhaustive_limit=plan.exhaustive_limit, overlap=plan.overlap)
        report.set_execution(work, colmap_options_used=cs.used, colmap_options_skipped=cs.skipped, memory_plan=plan.as_dict())
        for opt in cs.skipped:
            ctx.log(f"COLMAP {caps.version}: optional {opt['option']} not available for {opt['command']}, left out ({opt['purpose']})")

        labels = {"feature_extractor": (12, f"COLMAP feature extraction on {total_images} images (CPU, {plan.tier} plan)"),
                  "exhaustive_matcher": (25, "COLMAP feature matching (exhaustive, CPU)"),
                  "sequential_matcher": (25, "COLMAP feature matching (sequential, CPU)"),
                  "mapper": (45, "COLMAP mapping (camera poses and sparse points)")}
        for label, argv in cs.commands:
            _memory_gate(ctx, label)
            pct, msg = labels[label]
            ctx.update("sfm", pct, msg)
            _run(argv, label, ctx, work / "colmap_logs")
            detail = {}
            if config.COLMAP_VALIDATE_DB and label == "feature_extractor":
                detail = colmap_validate.validate_features(db, total_images)
            elif config.COLMAP_VALIDATE_DB and label in ("exhaustive_matcher", "sequential_matcher"):
                detail = colmap_validate.validate_matches(db, total_images)
            report.stage(work, f"colmap_{label}", "ok", f"{label} finished", plan=plan.tier, database=detail or None)

        model_dir, registered, model_counts = _best_model(work, ctx, caps)
        if len(model_counts) > 1:
            # COLMAP split the video into separate, unrelated 3D models. Frames in the other models share no landmarks with this one,
            # so they cannot be linked to it: say so instead of silently losing them.
            ctx.log(f"COLMAP produced {len(model_counts)} separate models with {sorted(model_counts, reverse=True)} registered images; using the largest")
            report.stage(work, "colmap_models", "ok", f"{len(model_counts)} separate sparse models; the largest was used",
                         registered_per_model=sorted(model_counts, reverse=True))
        if model_dir is None or registered < 6:
            raise PipelineError(f"COLMAP registered only {registered} of {total_images} images, which is not enough for a model. "
                                "Film slowly, keep objects in view across frames, avoid blank walls and low light.", 422)
        cams = geometry.parse_cameras((model_dir / "cameras.txt").read_text())
        poses = geometry.parse_images((model_dir / "images.txt").read_text())
        points, colors, point_ids = geometry.parse_points_ex((model_dir / "points3D.txt").read_text())
        row_of = {pid: row for row, pid in enumerate(point_ids)}
        raw_obs = geometry.parse_image_observations((model_dir / "images.txt").read_text())
        # landmark observations per image, in the row space of the returned point array (only well-triangulated points)
        observations = {name: sorted(row_of[i] for i in ids if i in row_of) for name, ids in raw_obs.items()}
    finally:
        shutil.rmtree(images, ignore_errors=True)  # the copies are only needed while COLMAP runs
        shutil.rmtree(work / "sparse_txt_tmp", ignore_errors=True)
    return {"cams": cams, "poses": poses, "points": points, "colors": colors, "total_images": total_images,
            "observations": observations,
            "meta": {"backend": "colmap", "sparse_models": len(model_counts), "registered_per_model": sorted(model_counts, reverse=True), "colmap_version": caps.version, "frames_used": len(used_frames),
                     "frames_registered": registered, "device": "cpu", "memory_plan": plan.tier,
                     "image_side": plan.max_side}}


def _colmap_with_retry(colmap, frames_dir, frames, work, is_360, ctx, plan, caps):
    """Run COLMAP; if a stage dies of memory exhaustion, step down one tier and try once more. Never loops."""
    try:
        return _colmap_sfm(colmap, frames_dir, frames, work, is_360, ctx, plan, caps)
    except ColmapOOM as e:
        lower = memory_plan.step_down(plan.tier)
        if lower is None:
            raise PipelineError(f"{e} Already in minimal-memory mode. Close other programs, lower FRAME_TARGET_FPS to 1, "
                                "record a shorter video, or add RAM.", 507) from e
        ctx.log(f"Out of memory in the {plan.tier} plan; retrying once with the {lower} plan")
        report.stage(work, "colmap_oom_retry", "ok", f"{plan.tier} plan ran out of memory; retried with {lower}")
        smaller = memory_plan.make_plan(hardware.available_ram_mb(), plan.threads, tier=lower)
        try:
            return _colmap_sfm(colmap, frames_dir, frames, work, is_360, ctx, smaller, caps)
        except ColmapOOM as e2:
            raise PipelineError(f"{e2} Even the {lower} plan did not fit. Close other programs, lower FRAME_TARGET_FPS to 1, "
                                "record a shorter video, or add RAM.", 507) from e2


def choose_backend(is_360: bool):
    loc = colmap_locator.locate()
    colmap = loc.path
    want = config.SFM_BACKEND
    if want == "colmap":
        if not colmap:
            raise PipelineError("SFM_BACKEND=colmap but COLMAP was not found (looked in: " + "; ".join(loc.tried) + "). Run scripts\\install-colmap.ps1 "
                                "or set COLMAP_BIN; no reconstruction was attempted.", 503)
        return "colmap", colmap
    if want == "opencv" or (want == "auto" and not colmap):
        if is_360:
            raise PipelineError("360° equirectangular video needs COLMAP (not found). The built-in OpenCV pipeline handles flat video only. "
                                "Run scripts\\install-colmap.ps1, or upload a normal video. No reconstruction was attempted.", 503)
        return "opencv", None
    return "colmap", colmap


def run(frames_rel: str, work_rel: str, is_360: bool, ctx=None):
    ctx = ctx or jobs.get(None)
    backend, colmap = choose_backend(is_360)
    frames_dir = config.resolve(frames_rel)
    meta = json.loads((frames_dir / "frames.json").read_text())
    frames = meta["frames"]
    work = config.resolve(work_rel)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    free = hardware.available_ram_mb()
    plan = memory_plan.make_plan(free, hardware.cpu_threads())   # raises with advice only below MIN_FREE_RAM_MB
    ctx.log(f"Free RAM {free} MB -> {plan.tier} plan: {plan.note}")

    dev = hardware.select_devices()
    report.set_execution(work, sfm_backend=backend, sfm_device="cpu", memory_plan=plan.as_dict(), free_ram_mb_at_start=free, open3d_device=dev["open3d_device"],
                         torch_device=dev["torch_device"], cpu_threads=hardware.cpu_threads(), device_notes=dev["notes"],
                         cuda_required=False)
    ctx.update("sfm", 11, f"Structure from motion with {'COLMAP' if backend == 'colmap' else 'the built-in OpenCV pipeline'} on the CPU")
    try:
        if backend == "colmap":
            caps = colmap_compat.get_caps(colmap)
            loc = colmap_locator.locate()
            report.set_execution(work, colmap=caps.summary(), colmap_location=loc.as_dict(), colmap_cuda=caps.cuda,
                                 colmap_dense_mvs=colmap_compat.dense_mvs_support(caps))
            res = _colmap_with_retry(colmap, frames_dir, frames, work, is_360, ctx, plan, caps)
        else:
            res = sfm.run(frames_dir, frames, ctx)
            res["total_images"] = res["meta"]["frames_used"]
            hardware.record_runtime_success("opencv_sfm")
        if backend == "colmap":
            hardware.record_runtime_success("colmap")
    except Cancelled:
        raise
    except PipelineError as e:
        report.stage(work, "camera_poses", "failed", str(e), backend=backend)
        raise
    ctx.update(progress=66, message="Normalising the coordinate frame and writing the sparse point cloud")

    cams, poses, points, colors = res["cams"], res["poses"], res["points"], res["colors"]
    total_images, registered = res["total_images"], len(poses)

    names = list(poses)
    centers = np.array([poses[n]["center"] for n in names])
    axes = np.array([poses[n]["axes"] for n in names])
    Rn, origin = geometry.world_normalisation(centers, axes, points)
    to_new = lambda p: (np.asarray(p) - origin) @ Rn.T  # noqa: E731

    new_points = to_new(points) if len(points) else np.zeros((0, 3))
    if len(new_points) >= 30:
        lo = np.percentile(new_points, 1, axis=0)
        hi = np.percentile(new_points, 99, axis=0)
        extents = {"x": float(hi[0] - lo[0]), "y": float(hi[1] - lo[1]), "z": float(hi[2] - lo[2])}
    else:
        c = to_new(centers)
        extents = {k: float(np.ptp(c[:, i])) for i, k in enumerate("xyz")}

    images_out = {}
    for n in names:
        images_out[n] = {"center": to_new(poses[n]["center"]).tolist(),
                         "axes": (poses[n]["axes"] @ Rn.T).tolist(),
                         "camera_id": poses[n]["camera_id"]}

    sample = np.random.default_rng(0).permutation(len(new_points))[:20000]
    preview = {"count": int(len(sample)), "units": "model_units",
               "positions": np.round(new_points[sample], 4).flatten().tolist(),
               "colors": colors[sample].flatten().tolist()}
    (work / "points_preview.json").write_text(json.dumps(preview))
    np.savez_compressed(work / "points_full.npz", positions=new_points.astype(np.float32), colors=colors.astype(np.uint8))
    obs = {n: [int(i) for i in res.get("observations", {}).get(n, [])] for n in names}
    (work / "observations.json").write_text(json.dumps({"version": 1, "landmarks": int(len(new_points)), "images": obs}))

    if is_360:
        registered_frames = {Path(n).stem.split("__")[0] for n in names}
        # a panorama node needs at least two of its four faces registered
        registered_frames = {s for s in registered_frames if sum(1 for n in names if n.startswith(s + "__")) >= 2}
    else:
        registered_frames = {Path(n).stem for n in names}
    frame_status = [{"stem": Path(f["name"]).stem, "name": f["name"], "file": f["file"], "t": f["t"],
                     "frame_index": f["frame_index"], "registered": Path(f["name"]).stem in registered_frames}
                    for f in frames]
    if len(registered_frames) < 4:
        report.stage(work, "camera_poses", "failed", f"Only {len(registered_frames)} frames were registered", backend=backend)
        raise PipelineError(f"Only {len(registered_frames)} frames were registered; cannot build a navigable tour.", 422)

    recon = {"is_360": is_360, "units": "model_units", "cameras": {str(k): v for k, v in cams.items()},
             "images": images_out, "frames": frame_status, "extents": extents,
             "total_images": total_images, "registered_images": registered, "point_count": int(len(new_points)),
             "sfm": res["meta"]}
    (work / "reconstruction.json").write_text(json.dumps(recon))
    report.stage(work, "camera_poses", "ok",
                 f"{registered} of {total_images} images registered, {len(new_points)} sparse points ({res['meta']['backend']})",
                 backend=res["meta"]["backend"], registered_images=registered, total_images=total_images,
                 points=int(len(new_points)), details=res["meta"])
    return {"registered_images": registered, "total_images": total_images,
            "registered_frames": len(registered_frames), "total_frames": len(frames),
            "points": int(len(new_points)), "extents_model_units": extents, "backend": res["meta"]["backend"]}
