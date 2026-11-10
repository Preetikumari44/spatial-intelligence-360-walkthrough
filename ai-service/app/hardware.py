"""
Runtime hardware detection and device selection.

Nothing here assumes CUDA or an NVIDIA GPU. An NVIDIA card that happens to be present is reported but never used.
The application is CPU-only: Open3D SYCL and PyTorch XPU are neither probed nor selected.
"""
import json
import logging
import os
import platform
import subprocess
import sys
import threading

from . import config

log = logging.getLogger("hardware")
_lock = threading.Lock()
_cache = {}


def cpu_threads() -> int:
    if config.CPU_THREADS > 0:
        return config.CPU_THREADS
    return max(1, (os.cpu_count() or 2) - 1)


def apply_thread_limits():
    """Called once at start-up so OpenCV, NumPy-backed libraries and PyTorch share the configured thread budget."""
    n = str(cpu_threads())
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(var, n)
    try:
        import cv2
        cv2.setNumThreads(cpu_threads())
    except ImportError:
        pass
    try:
        import torch
        torch.set_num_threads(cpu_threads())
    except Exception:  # torch is optional until Gaussian splatting runs
        pass


def memory():
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {"total_mb": int(vm.total / 1048576), "available_mb": int(vm.available / 1048576)}
    except Exception:
        return {"total_mb": None, "available_mb": None}


def available_ram_mb():
    return memory()["available_mb"]


def intel_gpus():
    """Names of Intel graphics adapters, found with the operating system's own tools. Empty if none or unknown."""
    names = []
    try:
        if platform.system() == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                capture_output=True, text=True, timeout=15).stdout
            names = [ln.strip() for ln in out.splitlines() if ln.strip()]
        elif platform.system() == "Linux":
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10).stdout
            names = [ln.split(": ", 1)[-1] for ln in out.splitlines() if "VGA" in ln or "Display" in ln or "3D controller" in ln]
    except Exception as e:  # tools missing or blocked: report unknown rather than guess
        log.info("GPU enumeration failed: %s", e)
    return {"adapters": names,
            "intel": [n for n in names if "intel" in n.lower()],
            "nvidia_present_but_unused": any("nvidia" in n.lower() for n in names)}


_SMOKE = r"""
import json, sys
import open3d as o3d, open3d.core as o3c
out = {"version": o3d.__version__}
try:
    import numpy as np
    points = np.random.default_rng(0).random((512, 3)).astype("float32")
    legacy = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    legacy = legacy.voxel_down_sample(0.08)
    legacy.estimate_normals()
    cpu = o3c.Device("CPU:0")
    tensor = o3d.t.geometry.PointCloud(o3c.Tensor(points, device=cpu))
    down = tensor.voxel_down_sample(0.08)
    out["cpu_smoke_ok"] = len(legacy.points) > 0 and legacy.has_normals() and int(down.point.positions.shape[0]) > 0
except Exception as e:
    out["cpu_smoke_ok"] = False
    out["cpu_error"] = str(e)
out["sycl_available"] = False
out["sycl_devices"] = []
out["sycl_smoke_ok"] = False
print("@@" + json.dumps(out))
"""


def open3d_info():
    with _lock:
        if "open3d" in _cache:
            return _cache["open3d"]
    info = {"installed": False}
    try:
        p = subprocess.run([sys.executable, "-c", _SMOKE], capture_output=True, text=True, timeout=config.XPU_SMOKE_TIMEOUT)
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("@@")), None)
        if line:
            info = {"installed": True, **json.loads(line[2:])}
        else:
            info = {"installed": False, "error": (p.stderr or "Open3D probe printed nothing")[-300:]}
    except subprocess.TimeoutExpired:
        info = {"installed": True, "cpu_smoke_ok": False,
                "error": f"Open3D CPU probe did not finish in {config.XPU_SMOKE_TIMEOUT}s and was stopped"}
    except Exception as e:
        info = {"installed": False, "error": str(e)}
    with _lock:
        _cache["open3d"] = info
    return info


def torch_info():
    with _lock:
        if "torch" in _cache:
            return _cache["torch"]
    info = {"installed": False}
    try:
        import torch
        info = {"installed": True, "version": torch.__version__, "xpu_available": False, "xpu_devices": []}
    except Exception as e:
        info = {"installed": False, "error": str(e)[:200]}
    with _lock:
        _cache["torch"] = info
    return info


def select_devices():
    """The devices the pipeline will actually try, with the reason for each choice."""
    o3 = open3d_info()
    tc = torch_info()
    notes = []
    want_xpu = config.XPU_MODE != "0"
    o3_dev = "CPU:0"
    if not want_xpu:
        notes.append("XPU_MODE=0: Intel acceleration disabled by configuration")
    elif o3.get("sycl_smoke_ok"):
        o3_dev = "SYCL:0"
    elif o3.get("installed"):
        notes.append("Open3D CPU operations are enabled; accelerator backends are disabled")
    else:
        notes.append("Open3D is not installed: " + str(o3.get("error", "")))
    t_dev = "cpu"
    if want_xpu and tc.get("xpu_available"):
        t_dev = "xpu"
    elif tc.get("installed") and want_xpu:
        notes.append("PyTorch has no XPU build or no Intel GPU visible; Gaussian training uses the CPU")
    elif not tc.get("installed"):
        notes.append("PyTorch is not installed: Gaussian training unavailable")
    return {"open3d_device": o3_dev, "torch_device": t_dev, "notes": notes}


def report():
    """Everything the UI shows on the Video Reconstruction page and in Settings."""
    import shutil
    mem = memory()
    gpus = intel_gpus()
    o3 = open3d_info()
    tc = torch_info()
    dev = select_devices()
    from . import colmap_locator
    loc = colmap_locator.locate()
    colmap = loc.found
    return {
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cpu": {"name": platform.processor() or platform.machine(), "logical_cores": os.cpu_count(), "threads_used": cpu_threads()},
        "memory": mem,
        "gpu": gpus,
        "open3d": o3, "torch": tc,
        "colmap": {"found": colmap, "source": loc.source, "path": loc.path, "gpu_used": False},
        "devices": dev,
        "sfm_backend": "colmap" if colmap and config.SFM_BACKEND in ("auto", "colmap") else
                       ("opencv" if config.SFM_BACKEND in ("auto", "opencv") else "unavailable"),
        "cuda_required": False,
    }


def peek():
    """Capability flags from whatever has already been probed; never blocks, so /health stays fast."""
    with _lock:
        o3 = _cache.get("open3d")
        tc = _cache.get("torch")
    return {"open3d": bool(o3 and o3.get("cpu_smoke_ok")),
            "open3d_sycl": bool(config.XPU_MODE != "0" and o3 and o3.get("sycl_smoke_ok")),
            "torch": bool(tc and tc.get("installed")),
            "torch_xpu": bool(config.XPU_MODE != "0" and tc and tc.get("xpu_available")),
            "probed": o3 is not None and tc is not None}


def probe():
    """Run cached hardware probes before returning capability flags; health must not report a startup race as missing."""
    open3d_info()
    torch_info()
    return peek()


def runtime_test(name, test):
    """Cache the result of a small real operation; importability alone is not a capability."""
    key = f"runtime:{name}"
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        result = bool(test())
    except Exception:
        log.exception("%s CPU capability smoke test failed", name)
        result = False
    with _lock:
        _cache[key] = result
    return result


def record_runtime_success(name):
    """Keep health reporting in sync with a capability proven by a successful real pipeline stage."""
    with _lock:
        _cache[f"runtime:{name}"] = True


def warm():
    """Probe CPU hardware in the background so service startup does not block."""
    def go():
        try:
            apply_thread_limits()
            open3d_info()
            torch_info()
        except Exception:
            log.exception("hardware probe failed")
    threading.Thread(target=go, name="hardware-probe", daemon=True).start()


def reset_cache():
    with _lock:
        _cache.clear()


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))(json.dumps(report(), indent=2))
