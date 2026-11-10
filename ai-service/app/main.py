import contextlib
import logging
import threading
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import colmap_compat, colmap_locator, config, dense, hardware, image_pipeline, jobs, panorama, reconstruct, report, sensors, sfm, splat, tour, video_pipeline, viewpoints
from .errors import Cancelled, PipelineError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-service")
app = FastAPI(title="Spatial AI service", version="0.2.0")

# One heavy job at a time per process, so two reconstructions can never exhaust a 16 GB laptop; the Java side queues the rest.
_heavy_lock = threading.Lock()


@app.on_event("startup")
def _startup():
    hardware.warm()


@app.exception_handler(PipelineError)
async def pipeline_error(_, exc: PipelineError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


class ImageReq(BaseModel):
    image_path: str


class ProbeReq(BaseModel):
    video_path: str
    is_360: bool = False


class FramesReq(BaseModel):
    video_path: str
    out_dir: str
    is_360: bool = False
    job_id: str | None = None


class ReconReq(BaseModel):
    frames_dir: str
    work_dir: str
    is_360: bool = False
    job_id: str | None = None


class TourReq(BaseModel):
    work_dir: str
    is_360: bool = False
    job_id: str | None = None
    fallback_tour: dict[str, Any] | None = None


class ViewpointReq(BaseModel):
    frames_dir: str
    work_dir: str
    is_360: bool = False
    job_id: str | None = None


class ModelReq(BaseModel):
    frames_dir: str
    work_dir: str
    job_id: str | None = None


def _ctx(job_id, anchor_rel, fresh=False):
    """The job's context, logging to <job folder>/ai.log. anchor_rel is any path inside the job folder (its frames or work dir)."""
    log_file = None
    if job_id:
        log_file = config.resolve(anchor_rel).parent / "ai.log"
    return jobs.get(job_id, log_file, fresh=fresh)


@contextlib.contextmanager
def _heavy(ctx):
    """Wait for the single heavy-job slot, staying cancellable while waiting."""
    announced = False
    while not _heavy_lock.acquire(timeout=1.0):
        ctx.check()
        if not announced:
            ctx.log("Waiting for another reconstruction to finish (one heavy job at a time)")
            announced = True
    try:
        ctx.check()
        yield
    finally:
        _heavy_lock.release()


@app.get("/health")
def health():
    flags = hardware.probe()

    def run_probe(name, fn):
        return hardware.runtime_test(name, fn)

    def colmap_cpu_probe():
        loc = colmap_locator.locate()
        if not loc.found or not colmap_locator.start_check(loc.path)["started"]:
            return False
        caps = colmap_compat.get_caps(loc.path)
        return (caps.supports("feature_extractor", *colmap_compat.GPU_EXTRACT)
                and caps.supports("exhaustive_matcher", *colmap_compat.GPU_MATCH)
                and caps.supports("mapper", "database_path", "image_path", "output_path"))

    detection = run_probe("detection_segmentation", image_pipeline.probe_detection_cpu)
    depth = run_probe("metric_depth", image_pipeline.probe_depth_cpu)
    colmap = run_probe("colmap", colmap_cpu_probe)
    opencv_sfm = run_probe("opencv_sfm", sfm.cpu_smoke_test)
    open3d = flags["open3d"]
    dense_mesh = open3d and depth and run_probe("dense_mesh", dense.cpu_smoke_test)
    gaussian_splatting = (config.SPLAT_ENABLED and flags["torch"]
                          and run_probe("gaussian_splatting", splat.cpu_smoke_test))
    return {
        "status": "ok",
        # booleans only: the Settings page renders each value as available / missing
        "capabilities": {
            "detection_segmentation": detection,
            "metric_depth": depth,
            "colmap": colmap,
            "opencv_sfm": opencv_sfm,
            "open3d": open3d,
            "open3d_sycl_xpu": False,
            "torch_xpu": False,
            "gaussian_splatting": gaussian_splatting,
            "dense_mesh": dense_mesh,
        },
    }


@app.get("/colmap/status")
def colmap_status():
    """Where COLMAP was found, whether it starts, its version, CUDA state and the Visual C++ runtime check. Starts the binary (cached)."""
    loc = colmap_locator.locate()
    out = {"location": loc.as_dict(), "bundle": colmap_locator.bundle_report(), "vc_runtime": colmap_locator.check_vc_runtime(),
           "start": None, "version": None, "cuda": None, "dense_mvs": None, "error": None}
    if not loc.found:
        out["error"] = "COLMAP not found: run scripts\\install-colmap.ps1"
        out["health"] = {"state": "not_installed" if not colmap_locator.bundle_report()["exe_present"] else "executable_missing", "ok": False}
        return out
    out["start"] = colmap_locator.start_check(loc.path)
    caps = None
    try:
        caps = colmap_compat.get_caps(loc.path)
        out.update(version=caps.version, cuda=caps.cuda, dense_mvs=colmap_compat.dense_mvs_support(caps), probe=caps.summary())
    except Exception as e:  # report, do not 500: this endpoint exists to diagnose a broken install
        out["error"] = str(e)
    # one overall verdict that tells the failure kinds apart
    st = out["start"]
    if not st["started"] and st.get("explanation") and "DLL" in st["explanation"]:
        state = "dll_missing"
    elif not st["started"]:
        state = "start_failed"
    elif caps is None:
        state = "unsupported_command" if "unusable" in (out["error"] or "") or "supports none" in (out["error"] or "") else "probe_failed"
    else:
        state = "ok"
    ops = caps.options if caps else {}
    out["capabilities"] = {"cpu": True, "cuda": caps.cuda if caps else None,
                           "feature_extraction": bool(ops.get("feature_extractor")), "matching": bool(ops.get("sequential_matcher") or ops.get("exhaustive_matcher")),
                           "mapping": bool(ops.get("mapper")), "dense_stereo": bool(out["dense_mvs"] and out["dense_mvs"]["supported"]),
                           "commands": sorted(ops.keys())}
    out["health"] = {"state": state, "ok": state == "ok"}
    return out


@app.get("/capabilities")
def capabilities():
    """Full hardware and software report: what was detected, which device each stage will try, and why."""
    return hardware.report()


@app.post("/image/analyze")
def image_analyze(req: ImageReq):
    with _heavy_lock:
        return image_pipeline.analyze(req.image_path)


@app.post("/video/probe")
def video_probe(req: ProbeReq):
    return video_pipeline.probe(req.video_path, req.is_360)


@app.post("/video/frames")
def video_frames(req: FramesReq):
    ctx = _ctx(req.job_id, req.out_dir, fresh=True)
    with _heavy(ctx):
        return video_pipeline.extract_frames(req.video_path, req.out_dir, req.is_360, ctx)


@app.post("/video/reconstruct")
def video_reconstruct(req: ReconReq):
    ctx = _ctx(req.job_id, req.work_dir)
    with _heavy(ctx):
        return reconstruct.run(req.frames_dir, req.work_dir, req.is_360, ctx)


@app.post("/video/viewpoints")
def video_viewpoints(req: ViewpointReq):
    """Pipeline A: the virtual tour from the extracted frames alone. Needs no COLMAP, no poses, no Open3D, no PyTorch."""
    ctx = _ctx(req.job_id, req.work_dir)
    with _heavy(ctx):
        return viewpoints.build(req.frames_dir, req.work_dir, req.is_360, ctx)


@app.post("/video/panoramas")
def video_panoramas(req: TourReq):
    """Stitch real 360 panoramas wherever the reconstruction has enough frames from one position. Honest coverage per panorama; nothing is invented."""
    return panorama.build_all(req.work_dir)


@app.post("/video/sensors")
def video_sensors(req: ProbeReq):
    """Which sensor metadata (GPS tag, motion tracks) the uploaded video really contains."""
    return sensors.inspect(config.resolve(req.video_path))


@app.post("/video/tour")
def video_tour(req: TourReq):
    return tour.build(req.work_dir, req.is_360, req.fallback_tour)


@app.post("/video/model")
def video_model(req: ModelReq):
    """Point cloud and mesh. A failure here is recorded in the report and returned as a stage status, never as a fake success."""
    ctx = _ctx(req.job_id, req.work_dir)
    work = config.resolve(req.work_dir)
    result = {}
    with _heavy(ctx):
        ctx.update("dense", 70, "Building the point cloud with Open3D")
        for name, fn in (("point_cloud", lambda: dense.build_pointcloud(req.work_dir, ctx)),
                         ("mesh", lambda: dense.build_mesh(req.work_dir, req.frames_dir, ctx))):
            ctx.check()
            try:
                result[name] = fn()
            except Cancelled:
                raise
            except PipelineError as e:
                report.stage(work, name, "failed", str(e))
                result[name] = {"status": "failed", "message": str(e)}
            except Exception as e:  # an unexpected bug must still show up in the report instead of killing the job
                log.exception("%s stage crashed", name)
                report.stage(work, name, "failed", f"{type(e).__name__}: {e}")
                result[name] = {"status": "failed", "message": str(e)}
    return result


@app.post("/video/splat")
def video_splat(req: ModelReq):
    ctx = _ctx(req.job_id, req.work_dir)
    work = config.resolve(req.work_dir)
    with _heavy(ctx):
        try:
            return splat.run_stage(req.work_dir, req.frames_dir, ctx)
        except Cancelled:
            raise
        except Exception as e:
            log.exception("splat stage crashed")
            report.stage(work, "gaussian_splat", "failed", f"{type(e).__name__}: {e}")
            return {"status": "failed", "message": str(e)}


@app.get("/jobs/{job_id}/status")
def job_status(job_id: str):
    ctx = jobs.peek(job_id)
    if ctx is None:
        return {"job_id": job_id, "known": False}
    return {"known": True, **ctx.snapshot()}


@app.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    ctx = jobs.get(job_id)
    ctx.cancel()
    ctx.log("Cancellation requested")
    return {"job_id": job_id, "cancelled": True}
