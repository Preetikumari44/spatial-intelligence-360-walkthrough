import os
from pathlib import Path

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "../data/storage")).resolve()

YOLO_MODEL = os.environ.get("YOLO_MODEL", "yolov8m-seg.pt")
DEPTH_ENABLED = os.environ.get("DEPTH_ENABLED", "1") == "1"
DEPTH_MODEL = os.environ.get("DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf")
DETECTION_CONF = float(os.environ.get("DETECTION_CONF", "0.25"))

MAX_VIDEO_SECONDS = float(os.environ.get("MAX_VIDEO_SECONDS", "900"))
MIN_VIDEO_SIDE = int(os.environ.get("MIN_VIDEO_SIDE", "360"))
FRAME_TARGET_FPS = float(os.environ.get("FRAME_TARGET_FPS", "3"))
# Virtual tour from frames alone (no COLMAP): how much visual overlap proves a link
TOUR_VERIFY_INLIERS = int(os.environ.get("TOUR_VERIFY_INLIERS", "25"))
TOUR_REVISIT_INLIERS = int(os.environ.get("TOUR_REVISIT_INLIERS", "45"))
# Verified viewpoint links (see viewgraph.py): two viewpoints are linked only if the reconstruction proves they see the same landmarks
TOUR_MIN_SHARED_LANDMARKS = int(os.environ.get("TOUR_MIN_SHARED_LANDMARKS", "20"))   # common 3D points seen from both viewpoints
TOUR_MIN_OVERLAP = float(os.environ.get("TOUR_MIN_OVERLAP", "0.12"))                 # shared / smaller landmark set
TOUR_MIN_PARALLAX_DEG = float(os.environ.get("TOUR_MIN_PARALLAX_DEG", "0.3"))        # median angle at which the two cameras see a shared point
TOUR_MAX_VIEW_ANGLE_DEG = float(os.environ.get("TOUR_MAX_VIEW_ANGLE_DEG", "100"))    # angle between the two optical axes
TOUR_LOOP_MIN_GAP_SEC = float(os.environ.get("TOUR_LOOP_MIN_GAP_SEC", "8"))          # a link between moments this far apart is a loop closure
# 0 (default): a link that cannot be verified is not created. 1: restore the old behaviour (video-order links even when frames do not overlap)
TOUR_ALLOW_UNVERIFIED_LINKS = os.environ.get("TOUR_ALLOW_UNVERIFIED_LINKS", "0") == "1"
FRAME_MAX = int(os.environ.get("FRAME_MAX", "400"))
# adaptive: sample by measured camera motion (default); fixed: every Nth frame at FRAME_TARGET_FPS (old behaviour)
FRAME_SAMPLING = os.environ.get("FRAME_SAMPLING", "adaptive").strip().lower()
FRAME_PROBE_FPS = float(os.environ.get("FRAME_PROBE_FPS", "8"))             # how often motion is measured (frames per second of video)
FRAME_MOTION_TARGET = float(os.environ.get("FRAME_MOTION_TARGET", "0.05"))  # accumulated image motion (fraction of frame width) between kept frames
FRAME_MAX_GAP_SEC = float(os.environ.get("FRAME_MAX_GAP_SEC", "2.5"))       # never leave a longer hole than this while the camera moves
FRAME_MIN_GAP_SEC = float(os.environ.get("FRAME_MIN_GAP_SEC", "0.12"))
FRAME_CUT_DIFF = float(os.environ.get("FRAME_CUT_DIFF", "38"))              # mean grey difference between probes that counts as a cut / room transition
FRAME_STATIC_MIN_MOTION = float(os.environ.get("FRAME_STATIC_MIN_MOTION", "0.25"))  # total motion below this = the camera never really moved
FRAME_MAX_SIDE = int(os.environ.get("FRAME_MAX_SIDE", "1600"))
FRAME_MAX_SIDE_360 = int(os.environ.get("FRAME_MAX_SIDE_360", "4096"))
BLUR_ABS_MIN = float(os.environ.get("BLUR_ABS_MIN", "10"))
DUP_DIFF = float(os.environ.get("DUP_DIFF", "2.5"))

# empty/"colmap" = use the bundled tools/colmap/bin/colmap.exe, else PATH; a full path here overrides the bundle (see colmap_locator.py)
COLMAP_BIN = os.environ.get("COLMAP_BIN", "").strip()
COLMAP_USE_GPU = os.environ.get("COLMAP_USE_GPU", "0")
COLMAP_TIMEOUT = int(os.environ.get("COLMAP_TIMEOUT", "7200"))
# check the COLMAP database after extraction/matching (keypoints per image, verified pairs); 0 only for debugging
COLMAP_VALIDATE_DB = os.environ.get("COLMAP_VALIDATE_DB", "1") == "1"
# sequential matching: also try loop closure when a vocabulary tree file is given (optional, not bundled)
COLMAP_VOCAB_TREE = os.environ.get("COLMAP_VOCAB_TREE", "").strip()


# --- hardware and memory (Intel CPU / Iris Xe friendly defaults) -------------------------------------------------------
# 0 = automatic (logical cores minus one, at least one)
CPU_THREADS = int(os.environ.get("CPU_THREADS", "0"))
# This application is intentionally CPU-only; Intel XPU/SYCL is never probed or selected.
XPU_MODE = "0"
XPU_SMOKE_TIMEOUT = int(os.environ.get("XPU_SMOKE_TIMEOUT", "90"))
# RAM that must stay free for the OS and the browser; heavy stages refuse to start below reserve + their own estimate
MEMORY_RESERVE_MB = int(os.environ.get("MEMORY_RESERVE_MB", "2500"))
# Reconstruction adapts to free RAM instead of refusing: >= NORMAL runs the configured quality, >= LOW runs a reduced plan,
# below that the minimal plan. Under MIN_FREE_RAM_MB the job is refused with advice. LOW_MEMORY_MODE forces a tier:
# auto, normal, low or minimal.
LOW_MEMORY_MODE = os.environ.get("LOW_MEMORY_MODE", "auto").strip().lower()
MEMORY_NORMAL_MB = int(os.environ.get("MEMORY_NORMAL_MB", "5500"))
MEMORY_LOW_MB = int(os.environ.get("MEMORY_LOW_MB", "2800"))
MIN_FREE_RAM_MB = int(os.environ.get("MIN_FREE_RAM_MB", "1200"))
MIN_FRAMES = int(os.environ.get("MIN_FRAMES", "8"))
FRAME_THUMB_SIDE = int(os.environ.get("FRAME_THUMB_SIDE", "240"))

# --- structure from motion ---------------------------------------------------------------------------------------------
# auto: COLMAP when found (flat or 360), otherwise the built-in OpenCV pipeline (flat video only)
SFM_BACKEND = os.environ.get("SFM_BACKEND", "auto").lower()
SFM_MAX_IMAGES = int(os.environ.get("SFM_MAX_IMAGES", "90"))
SFM_MAX_SIDE = int(os.environ.get("SFM_MAX_SIDE", "960"))
SFM_FEATURES = int(os.environ.get("SFM_FEATURES", "4000"))
SFM_MATCH_WINDOW = int(os.environ.get("SFM_MATCH_WINDOW", "6"))
# optional JSON file {"fx":..,"fy":..,"cx":..,"cy":..,"width":..,"height":..} from scripts/calibrate_camera.py
CAMERA_INTRINSICS_FILE = os.environ.get("CAMERA_INTRINSICS_FILE", "")

# --- dense geometry (Open3D) -------------------------------------------------------------------------------------------
DENSE_VOXELS = int(os.environ.get("DENSE_VOXELS", "160"))      # voxels along the longest scene axis
DENSE_MAX_FRAMES = int(os.environ.get("DENSE_MAX_FRAMES", "40"))
DENSE_DEPTH_SIDE = int(os.environ.get("DENSE_DEPTH_SIDE", "384"))
ICP_REFINE = os.environ.get("ICP_REFINE", "0") == "1"

# --- Gaussian splatting (CPU-capable trainer written in PyTorch) -------------------------------------------------------
SPLAT_ENABLED = os.environ.get("SPLAT_ENABLED", "1") == "1"
SPLAT_MAX_GAUSSIANS = int(os.environ.get("SPLAT_MAX_GAUSSIANS", "4000"))
SPLAT_MAX_SIDE = int(os.environ.get("SPLAT_MAX_SIDE", "128"))
SPLAT_ITERATIONS = int(os.environ.get("SPLAT_ITERATIONS", "300"))
SPLAT_TIME_BUDGET_SEC = int(os.environ.get("SPLAT_TIME_BUDGET_SEC", "900"))
SPLAT_MIN_VIEWS = int(os.environ.get("SPLAT_MIN_VIEWS", "6"))


def resolve(relative: str) -> Path:
    p = (STORAGE_ROOT / relative).resolve()
    if STORAGE_ROOT not in p.parents and p != STORAGE_ROOT:
        raise ValueError("path escapes storage root")
    return p


def relative(path: Path) -> str:
    return path.resolve().relative_to(STORAGE_ROOT).as_posix()
