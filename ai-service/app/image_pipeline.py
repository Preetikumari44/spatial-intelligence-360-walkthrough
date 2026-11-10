"""Object detection + instance segmentation + monocular metric depth for single photos."""
import logging
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import config, hardware
from .errors import PipelineError

log = logging.getLogger("image")

DEFAULT_F35 = 26.0  # typical phone main camera, 35mm-equivalent; used only when EXIF has no focal length


@lru_cache(maxsize=1)
def _yolo():
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise PipelineError("ultralytics is not installed in the AI service", 503) from e
    return YOLO(config.YOLO_MODEL)


@lru_cache(maxsize=1)
def _depth_pipe():
    if not config.DEPTH_ENABLED:
        return None
    try:
        from transformers import pipeline
        return pipeline("depth-estimation", model=config.DEPTH_MODEL, device=-1)
    except Exception as e:  # missing package, offline model download, out of memory
        log.warning("metric depth model unavailable, measurements will be skipped: %s", e)
        return None


def _intrinsics(path, width, height):
    f35 = None
    try:
        exif = Image.open(path).getexif()
        f35 = exif.get_ifd(0x8769).get(41989)  # FocalLengthIn35mmFilm
    except Exception:
        pass
    source = "exif"
    if not f35:
        f35, source = DEFAULT_F35, "assumed_26mm_equiv"
    # 35mm equivalent focal length is defined against a 36mm long side
    f_px = float(f35) / 36.0 * max(width, height)
    return {"fx": f_px, "fy": f_px, "cx": width / 2, "cy": height / 2, "source": source}


def _depth_map(bgr):
    pipe = _depth_pipe()
    if pipe is None:
        return None
    out = pipe(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    d = out["predicted_depth"].squeeze().float().cpu().numpy()
    return cv2.resize(d, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_LINEAR)


def estimate_dimensions(mask, depth, k, det_conf):
    """
    Back-project the object's mask pixels with metric depth and take robust extents.
    Depth extent is the visible surface only, not the object's true depth.
    Returns None when the mask is too small to say anything.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) < 300:
        return None
    rng = np.random.default_rng(0)
    pick = rng.choice(len(xs), min(len(xs), 20000), replace=False)
    xs, ys = xs[pick], ys[pick]
    z = depth[ys, xs].astype(np.float64)
    ok = (z > 0.2) & (z < 20.0)
    if ok.sum() < 200:
        return None
    xs, ys, z = xs[ok], ys[ok], z[ok]
    x = (xs - k["cx"]) * z / k["fx"]
    y = (ys - k["cy"]) * z / k["fy"]

    def span(v):
        lo, hi = np.percentile(v, [2, 98])
        return float(hi - lo)

    spread = float(np.std(z) / max(np.median(z), 1e-6))
    coverage = min(1.0, len(xs) / 5000.0) ** 0.5
    # a reliability heuristic, not a probability: capped because monocular depth is never survey-grade
    reliability = min(0.6, det_conf * coverage / (1.0 + spread))
    if k["source"] != "exif":
        reliability *= 0.7
    return {
        "width_mm": round(span(x) * 1000.0, 1),
        "height_mm": round(span(y) * 1000.0, 1),
        "depth_mm": round(span(z) * 1000.0, 1),
        "confidence": round(reliability, 3),
        "method": "monocular_metric_depth",
        "note": ("Estimated from a single photo with a monocular metric-depth model; intrinsics "
                 + ("from EXIF" if k["source"] == "exif" else "assumed (no EXIF focal length)")
                 + ". Depth is the visible-surface extent. Calibrate with a reference object to improve."),
    }


def _polygon(contour_xy):
    pts = np.asarray(contour_xy, dtype=np.float32).reshape(-1, 1, 2)
    if len(pts) < 3:
        return []
    eps = 0.003 * cv2.arcLength(pts, True)
    approx = cv2.approxPolyDP(pts, eps, True).reshape(-1, 2)
    return [[round(float(a), 1), round(float(b), 1)] for a, b in approx]


def analyze(image_rel: str):
    path = config.resolve(image_rel)
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise PipelineError("The file could not be decoded as an image")
    h, w = bgr.shape[:2]
    k = _intrinsics(path, w, h)

    res = _yolo().predict(bgr, conf=config.DETECTION_CONF, retina_masks=True, verbose=False, device="cpu")[0]
    hardware.record_runtime_success("detection_segmentation")
    depth = _depth_map(bgr)
    if depth is not None and np.isfinite(depth).all():
        hardware.record_runtime_success("metric_depth")

    objects = []
    n = 0 if res.boxes is None else len(res.boxes)
    for i in range(n):
        label = res.names[int(res.boxes.cls[i])]
        conf = float(res.boxes.conf[i])
        x1, y1, x2, y2 = [round(float(v), 1) for v in res.boxes.xyxy[i].tolist()]
        polygon, dims = [], None
        if res.masks is not None:
            polygon = _polygon(res.masks.xy[i])
            if depth is not None:
                mask = res.masks.data[i].cpu().numpy() > 0.5
                if mask.shape != depth.shape:
                    mask = cv2.resize(mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
                dims = estimate_dimensions(mask, depth, k, conf)
        objects.append({
            "label": label, "category": label, "confidence": round(conf, 3),
            "bbox": [x1, y1, x2, y2], "polygon": polygon, "dimensions": dims,
        })
    objects.sort(key=lambda o: -o["confidence"])
    return {
        "image": {"width": w, "height": h, "intrinsics": k},
        "depth_available": depth is not None,
        "detector": config.YOLO_MODEL,
        "objects": objects,
    }


@lru_cache(maxsize=1)
def probe_detection_cpu() -> bool:
    """Verify local segmentation weights with a real CPU inference without downloading a model."""
    if not Path(config.YOLO_MODEL).is_file():
        log.warning("Detection capability is unavailable: local YOLO weights '%s' were not found", config.YOLO_MODEL)
        return False
    model = _yolo()
    if getattr(model, "task", None) != "segment":
        return False
    result = model.predict(np.zeros((96, 96, 3), dtype=np.uint8), device="cpu", verbose=False)
    return len(result) == 1 and result[0].boxes is not None


@lru_cache(maxsize=1)
def probe_depth_cpu() -> bool:
    """Verify the configured metric-depth model using cached files and CPU inference only."""
    if not config.DEPTH_ENABLED:
        return False
    model_path = Path(config.DEPTH_MODEL)
    if not model_path.is_dir():
        from huggingface_hub import snapshot_download
        model_path = Path(snapshot_download(config.DEPTH_MODEL, local_files_only=True))
    from transformers import pipeline
    probe = pipeline("depth-estimation", model=str(model_path), device=-1)
    output = probe(Image.new("RGB", (96, 96), color=(96, 96, 96)))
    depth = np.asarray(output["predicted_depth"].squeeze().float().cpu())
    return depth.ndim == 2 and depth.size > 0 and bool(np.isfinite(depth).all())
