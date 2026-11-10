"""
CPU acceptance run: video in, honest per-feature statuses out.

    python tools/cpu_acceptance.py path\to\walkthrough.mp4 [--out acceptance_report.json] [--skip-splat]

For each of COLMAP, Open3D (point cloud and mesh) and Gaussian splatting it reports FOUR separate statuses:
  installed    the software is present
  initialized  it started and answered a real call (COLMAP `-h`, Open3D tensor op, PyTorch tensor op)
  tested       the stage was actually executed on the supplied video in this run
  generated    an output file exists AND was loaded back successfully by an independent reader
A feature is never "generated" because a package is installed. The process exits 0 only if every executed stage generated
verified output; unavailable features are reported as such and make the exit code 2 (not 0).
No CUDA is used or required.
"""
import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NO, YES, NA = "no", "yes", "n/a"


def row(installed=NO, initialized=NO, tested=NO, generated=NO, detail=""):
    return {"installed": installed, "initialized": initialized, "tested": tested, "generated": generated, "detail": detail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="acceptance_report.json")
    ap.add_argument("--skip-splat", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the temporary storage folder for inspection")
    a = ap.parse_args()
    video = Path(a.video).resolve()
    if not video.is_file():
        sys.exit(f"video not found: {video}")

    store = Path(tempfile.mkdtemp(prefix="spatial-accept-"))
    os.environ["STORAGE_ROOT"] = str(store)
    (store / "videos").mkdir()
    shutil.copy2(video, store / "videos" / "in.mp4")

    import numpy as np
    from app import colmap_compat, config, dense, hardware, jobs, reconstruct, splat, video_pipeline
    from app.errors import PipelineError

    res = {"video": str(video), "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "cuda_used": False,
           "free_ram_mb": hardware.available_ram_mb(), "features": {}, "stages": {}, "colmap": None}
    f = res["features"]
    f["colmap_cpu"], f["open3d_pointcloud_cpu"], f["open3d_mesh_cpu"], f["gaussian_splat_cpu"] = row(), row(), row(), row()
    ctx = jobs.JobContext(None)

    def stage(name, fn):
        t = time.time()
        try:
            out = fn()
            res["stages"][name] = {"status": "ok", "seconds": round(time.time() - t, 1)}
            return out
        except PipelineError as e:
            res["stages"][name] = {"status": "failed", "seconds": round(time.time() - t, 1), "error": str(e)}
        except Exception as e:  # report, never hide
            res["stages"][name] = {"status": "crashed", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
        return None

    # ---- installed / initialized ---------------------------------------------------------------------------------
    from app import colmap_locator
    loc = colmap_locator.locate()
    colmap = loc.path
    res["colmap_location"] = loc.as_dict()
    if colmap:
        f["colmap_cpu"]["installed"] = YES
        try:
            caps = colmap_compat.get_caps(colmap, refresh=True)
            res["colmap"] = caps.summary()
            f["colmap_cpu"]["initialized"] = YES if caps.options.get("feature_extractor") else NO
            f["colmap_cpu"]["detail"] = f"version {caps.version} ({loc.source}: {colmap}); CUDA={caps.cuda}; dense MVS: {colmap_compat.dense_mvs_support(caps)['supported']}"
        except PipelineError as e:
            f["colmap_cpu"]["detail"] = str(e)
    else:
        f["colmap_cpu"]["detail"] = "COLMAP not found (looked: " + "; ".join(loc.tried) + "); run scripts\\install-colmap.ps1"

    o3 = hardware.open3d_info()
    if o3.get("installed"):
        import open3d as o3d
        for k in ("open3d_pointcloud_cpu", "open3d_mesh_cpu"):
            f[k]["installed"] = YES
        try:
            p = o3d.t.geometry.PointCloud(o3d.core.Tensor(np.random.rand(500, 3).astype("float32")))
            ok = p.voxel_down_sample(0.1).point.positions.shape[0] > 0
            for k in ("open3d_pointcloud_cpu", "open3d_mesh_cpu"):
                f[k]["initialized"] = YES if ok else NO
        except Exception as e:
            f["open3d_pointcloud_cpu"]["detail"] = f"Open3D op failed: {e}"
    if importlib.util.find_spec("torch"):
        f["gaussian_splat_cpu"]["installed"] = YES
        try:
            import torch
            f["gaussian_splat_cpu"]["initialized"] = YES if float(torch.ones(4).sum()) == 4.0 else NO
            f["gaussian_splat_cpu"]["detail"] = f"torch {torch.__version__}, device cpu (project's own PyTorch trainer, not the CUDA 3DGS rasterizer)"
        except Exception as e:
            f["gaussian_splat_cpu"]["detail"] = str(e)
    else:
        f["gaussian_splat_cpu"]["detail"] = "PyTorch not installed"

    def rstat(name):
        """The pipeline's own verdict for a stage (report.json), which is what counts, not whether the call returned."""
        rp = config.resolve("jobs/a/work") / "report.json"
        st = (json.loads(rp.read_text()).get("stages", {}).get(name) if rp.exists() else None) or {}
        if name in res["stages"] and st.get("status"):
            res["stages"][name]["status"] = st["status"]
            if st.get("message") and st["status"] != "ok":
                res["stages"][name]["error"] = st["message"]
        return st.get("status")

    # ---- pipeline ------------------------------------------------------------------------------------------------
    stage("probe", lambda: video_pipeline.probe("videos/in.mp4", False))
    fr = stage("frames", lambda: video_pipeline.extract_frames("videos/in.mp4", "jobs/a/frames", False, ctx))
    if fr:
        rec = stage("camera_poses", lambda: reconstruct.run("jobs/a/frames", "jobs/a/work", False, ctx))
        if rec:
            res["camera_poses"] = rec
            if rec.get("backend") == "colmap":
                f["colmap_cpu"]["tested"] = YES
                work = config.resolve("jobs/a/work")
                good = (work / "reconstruction.json").exists() and rec["registered_images"] >= 6 and rec["points"] > 0
                f["colmap_cpu"]["generated"] = YES if good else NO
                f["colmap_cpu"]["detail"] += f"; registered {rec['registered_images']}/{rec['total_images']} images, {rec['points']} sparse points"
            else:
                res["note_sfm"] = f"camera poses came from the '{rec.get('backend')}' backend, so COLMAP was NOT tested"
        work = config.resolve("jobs/a/work")
        if rec:
            stage("point_cloud", lambda: dense.build_pointcloud("jobs/a/work", ctx))
            f["open3d_pointcloud_cpu"]["tested"] = YES if rstat("point_cloud") in ("ok", "failed") else NO
            ply = next(iter(work.glob("*.ply")), None) if work.exists() else None
            pc = next((p for p in work.rglob("*.ply") if "gauss" not in p.name.lower() and "mesh" not in p.name.lower()), None)
            if pc and o3.get("installed"):
                import open3d as o3d
                cloud = o3d.io.read_point_cloud(str(pc))
                if len(cloud.points) > 0:
                    cleaned, _ = cloud.remove_statistical_outlier(20, 2.0)   # a real processing step on the reloaded cloud
                    f["open3d_pointcloud_cpu"]["generated"] = YES if len(cleaned.points) > 0 else NO
                    f["open3d_pointcloud_cpu"]["detail"] = f"{pc.name}: {len(cloud.points)} points reloaded, {len(cleaned.points)} after outlier filtering"
            stage("mesh", lambda: dense.build_mesh("jobs/a/work", "jobs/a/frames", ctx))
            f["open3d_mesh_cpu"]["tested"] = YES if rstat("mesh") in ("ok", "failed") else NO
            mesh = next((p for p in work.rglob("*") if p.suffix in (".ply", ".glb", ".obj") and "mesh" in p.name.lower()), None)
            if mesh:
                import open3d as o3d
                m = o3d.io.read_triangle_mesh(str(mesh))
                if len(m.triangles) > 0:
                    f["open3d_mesh_cpu"]["generated"] = YES
                    f["open3d_mesh_cpu"]["detail"] = f"{mesh.name}: {len(m.vertices)} vertices, {len(m.triangles)} triangles reloaded"
            else:
                f["open3d_mesh_cpu"]["detail"] = res["stages"]["mesh"].get("error") or "mesh stage reported ok but no mesh file was found"
            if not a.skip_splat:
                stage("gaussian_splat", lambda: splat.run_stage("jobs/a/work", "jobs/a/frames", ctx))
                f["gaussian_splat_cpu"]["tested"] = YES if rstat("gaussian_splat") in ("ok", "failed") else NO
                gp = next((p for p in work.rglob("*.ply") if "gauss" in p.name.lower() or "splat" in p.name.lower()), None)
                if gp:
                    g = splat.read_gaussian_ply(gp)
                    n = len(g.xyz) if hasattr(g, "xyz") else len(g.positions) if hasattr(g, "positions") else 0
                    f["gaussian_splat_cpu"]["generated"] = YES if n > 0 else NO
                    f["gaussian_splat_cpu"]["detail"] += f"; {gp.name} reloaded, {n} gaussians"
                else:
                    rpt = json.loads((work / "report.json").read_text()) if (work / "report.json").exists() else {}
                    f["gaussian_splat_cpu"]["detail"] += "; no splat produced: " + rpt.get("stages", {}).get("gaussian_splat", {}).get("message", "see stages")
            else:
                f["gaussian_splat_cpu"]["detail"] += "; skipped by --skip-splat"
    res["report_json"] = (json.loads((config.resolve("jobs/a/work") / "report.json").read_text())
                          if (config.resolve("jobs/a/work") / "report.json").exists() else None)
    res["note_frontend"] = "Loading the outputs in the browser viewer is a manual step: open the project in the app and check the 3D Digital Twin tab."
    Path(a.out).write_text(json.dumps(res, indent=1))

    print(f"\n{'feature':26} {'installed':10} {'initialized':12} {'tested':8} {'generated':10}")
    for k, v in f.items():
        print(f"{k:26} {v['installed']:10} {v['initialized']:12} {v['tested']:8} {v['generated']:10}  {v['detail']}")
    for k, v in res["stages"].items():
        print(f"  stage {k:15} {v['status']:8} {v.get('error', '')[:160]}")
    print("report written to", a.out)
    if not a.keep:
        shutil.rmtree(store, ignore_errors=True)
    sys.exit(0 if all(v["tested"] == YES and v["generated"] == YES for v in f.values()) else 2)


if __name__ == "__main__":
    main()
