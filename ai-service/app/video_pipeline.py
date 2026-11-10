"""Video ingestion and frame selection (sharp, non-duplicate, timestamped frames)."""
import json
import shutil
import time

import cv2
import numpy as np

from . import config, hardware, jobs
from .errors import PipelineError


def probe(video_rel: str, is_360: bool = False):
    path = config.resolve(video_rel)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise PipelineError("The video could not be opened; the format or codec may be unsupported")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ok, _ = cap.read()
    cap.release()
    if not ok or w == 0 or h == 0 or fps <= 0:
        raise PipelineError("The video has no readable frames")
    duration = n / fps if n else 0.0
    if min(w, h) < config.MIN_VIDEO_SIDE:
        raise PipelineError(f"Resolution {w}x{h} is too low; at least {config.MIN_VIDEO_SIDE}px on the short side is required")
    if duration > config.MAX_VIDEO_SECONDS:
        raise PipelineError(f"Video is {duration:.0f}s; the limit is {config.MAX_VIDEO_SECONDS:.0f}s")
    ratio = w / h
    looks_equirect = abs(ratio - 2.0) < 0.05
    if is_360 and not looks_equirect:
        raise PipelineError(f"Marked as 360 but the frame is {w}x{h}; equirectangular video must be 2:1")
    warnings = []
    if looks_equirect and not is_360:
        warnings.append("Frame is 2:1; if this is 360 footage, upload it with the 360 option")
    return {"width": w, "height": h, "fps": fps, "frame_count": n, "duration_sec": round(duration, 2),
            "looks_equirectangular": looks_equirect, "warnings": warnings}


def _blur_score(gray):
    small = cv2.resize(gray, (960, int(960 * gray.shape[0] / gray.shape[1])), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(small, cv2.CV_64F).var())


def select_frames(candidates, blur_abs_min=None, dup_diff=None, max_frames=None):
    """
    candidates: dicts with 'blur' and 'thumb' (small grayscale array), in time order.
    Drops blurry frames, then frames too similar to the last kept one, then thins evenly to max_frames.
    """
    blur_abs_min = config.BLUR_ABS_MIN if blur_abs_min is None else blur_abs_min
    dup_diff = config.DUP_DIFF if dup_diff is None else dup_diff
    max_frames = config.FRAME_MAX if max_frames is None else max_frames
    if not candidates:
        return [], {"dropped_blur": 0, "dropped_duplicate": 0, "dropped_cap": 0}
    median = float(np.median([c["blur"] for c in candidates]))
    blur_min = max(blur_abs_min, 0.4 * median)
    kept, last, dropped_blur, dropped_dup = [], None, 0, 0
    for c in candidates:
        if c["blur"] < blur_min:
            dropped_blur += 1
            continue
        if last is not None and float(np.mean(cv2.absdiff(c["thumb"], last["thumb"]))) < dup_diff:
            dropped_dup += 1
            continue
        kept.append(c)
        last = c
    dropped_cap = 0
    if len(kept) > max_frames:
        idx = np.linspace(0, len(kept) - 1, max_frames).round().astype(int)
        thinned = [kept[i] for i in sorted(set(idx.tolist()))]
        dropped_cap = len(kept) - len(thinned)
        kept = thinned
    return kept, {"dropped_blur": dropped_blur, "dropped_duplicate": dropped_dup, "dropped_cap": dropped_cap}


def ram_limited_side(is_360: bool):
    """Longest frame side allowed by the free RAM. Integrated graphics share system memory, so be conservative."""
    cap = config.FRAME_MAX_SIDE_360 if is_360 else config.FRAME_MAX_SIDE
    free = hardware.available_ram_mb()
    if free is None:
        return cap, free
    usable = free - config.MEMORY_RESERVE_MB
    if usable < 1500:
        limit = 640
    elif usable < 3500:
        limit = 960
    elif usable < 6500:
        limit = 1280
    else:
        limit = cap
    return min(cap, limit), free


def _contact_sheet(thumbs, out_path, columns=6, rows=3):
    """A single preview image of evenly spaced kept frames, labelled with their timestamps."""
    pick = [thumbs[i] for i in np.linspace(0, len(thumbs) - 1, min(len(thumbs), columns * rows)).round().astype(int)]
    cells = []
    for img, t in pick:
        cell = cv2.resize(img, (200, 112), interpolation=cv2.INTER_AREA)
        cv2.putText(cell, f"{t:.1f}s", (6, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(cell)
    while len(cells) % columns:
        cells.append(np.zeros_like(cells[0]))
    grid = np.vstack([np.hstack(cells[r:r + columns]) for r in range(0, len(cells), columns)])
    cv2.imwrite(str(out_path), grid, [cv2.IMWRITE_JPEG_QUALITY, 80])


def extract_frames(video_rel: str, out_rel: str, is_360: bool, ctx=None):
    ctx = ctx or jobs.get(None)
    if config.FRAME_SAMPLING == "adaptive":
        return _extract_adaptive(video_rel, out_rel, is_360, ctx)
    return _extract_fixed(video_rel, out_rel, is_360, ctx)


def _extract_fixed(video_rel: str, out_rel: str, is_360: bool, ctx):
    info = probe(video_rel, is_360)
    cap = cv2.VideoCapture(str(config.resolve(video_rel)))
    out = config.resolve(out_rel)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "thumbs").mkdir()

    max_side, free_mb = ram_limited_side(is_360)
    step = max(1, round(info["fps"] / config.FRAME_TARGET_FPS))
    total = max(info["frame_count"], 1)
    ctx.update("frames", 2, f"Extracting every {step}th frame (about {info['fps'] / step:.1f} fps), longest side {max_side}px, "
                            f"free RAM {free_mb if free_mb is not None else 'unknown'} MB")
    # only small grey thumbnails stay in memory; full frames go straight to disk
    candidates, index = [], -1
    while cap.grab():
        index += 1
        if index % step:
            continue
        ctx.check()
        ok, frame = cap.retrieve()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if max(h, w) > max_side:
            s = max_side / max(h, w)
            frame = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        name = f"f_{index:06d}.jpg"
        cv2.imwrite(str(out / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        candidates.append({
            "file": name, "frame_index": index, "t": round(index / info["fps"], 3),
            "blur": _blur_score(gray), "thumb": cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA),
        })
        if len(candidates) % 10 == 0:
            ctx.update(progress=2 + 8 * index / total)
    cap.release()

    kept, drops = select_frames(candidates)
    keep_names = {c["file"] for c in kept}
    for c in candidates:
        if c["file"] not in keep_names:
            (out / c["file"]).unlink(missing_ok=True)

    if len(kept) < config.MIN_FRAMES:
        raise PipelineError(f"Only {len(kept)} usable frames after removing blur and duplicates (at least {config.MIN_FRAMES} are needed); "
                            "record slower, with better light and more camera movement")

    return _write_outputs(out, out_rel, kept, candidates, drops, info, is_360, ctx, {
        "sampling": "fixed",
        "settings": {"frame_step": step, "effective_fps": round(info["fps"] / step, 2), "max_side_px": max_side,
                     "free_ram_mb_at_start": free_mb, "min_frames_required": config.MIN_FRAMES}})


def _write_outputs(out, out_rel, kept, candidates, drops, info, is_360, ctx, extra):
    """Thumbnails, ordered preview sheet, frames.json and the summary the UI shows. Shared by both sampling modes."""
    sheet_src = []
    for c in kept:
        img = cv2.imread(str(out / c["file"]))
        if img is None:
            continue
        h, w = img.shape[:2]
        s = config.FRAME_THUMB_SIDE / max(h, w)
        thumb = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out / "thumbs" / c["file"]), thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
        sheet_src.append((thumb, c["t"]))
    _contact_sheet(sheet_src, out / "preview.jpg")   # a preview for people only; never used as a reconstruction input

    frames = [{"file": f"{out_rel}/{c['file']}", "name": c["file"], "frame_index": c["frame_index"], "t": c["t"],
               "blur": round(c["blur"], 1), "thumb": f"{out_rel}/thumbs/{c['file']}",
               **({"transition": True} if c.get("transition") else {}),
               **({"motion_since_previous": round(c["motion"], 3)} if "motion" in c else {})} for c in kept]
    summary = {"sampled": len(candidates), "kept": len(kept), **drops, "is_360": is_360,
               "source": info, "warnings": list(info["warnings"]) + list(extra.pop("warnings", [])),
               "source_frames": info["frame_count"], "duration_sec": info["duration_sec"],
               "resolution": {"source": [info["width"], info["height"]]},
               "preview": f"{out_rel}/preview.jpg", **extra}
    (out / "frames.json").write_text(json.dumps({"summary": summary, "frames": frames}))
    ctx.update(progress=10, message=f"Kept {len(kept)} of {len(candidates)} sampled frames "
                                    f"({drops['dropped_blur']} blurry, {drops['dropped_duplicate']} near-duplicate removed)")
    return summary


def _shift_and_diff(prev_gray, gray):
    """Image motion between two small grey frames: translation by phase correlation (fraction of width) and mean grey change."""
    a = prev_gray.astype(np.float32)
    b = gray.astype(np.float32)
    (dx, dy), response = cv2.phaseCorrelate(a, b)
    shift = float(np.hypot(dx, dy)) / a.shape[1]
    diff = float(np.mean(cv2.absdiff(prev_gray, gray)))
    return shift, diff, float(response)


def plan_adaptive(probes, *, motion_target=None, max_gap=None, min_gap=None, cut_diff=None, blur_abs_min=None, dup_diff=None):
    """
    probes: time-ordered dicts with t, blur, thumb (small grey array). Returns (chosen probes, stats).
    Rules:
      * motion between consecutive probes is accumulated; a segment closes when accumulated motion reaches the target
        (so consecutive kept frames overlap), when MAX_GAP seconds pass while the camera moves, or at a scene cut
      * the sharpest probe of a segment is kept; a segment with no usable (sharp) probe is dropped and counted as blurry
      * a cut (large grey change) keeps the last frame before it and the first after it, so room transitions survive
      * a segment that closed on time alone with almost no motion is a duplicate hold and is dropped
    """
    motion_target = config.FRAME_MOTION_TARGET if motion_target is None else motion_target
    max_gap = config.FRAME_MAX_GAP_SEC if max_gap is None else max_gap
    min_gap = config.FRAME_MIN_GAP_SEC if min_gap is None else min_gap
    cut_diff = config.FRAME_CUT_DIFF if cut_diff is None else cut_diff
    blur_abs_min = config.BLUR_ABS_MIN if blur_abs_min is None else blur_abs_min
    dup_diff = config.DUP_DIFF if dup_diff is None else dup_diff
    stats = {"dropped_blur": 0, "dropped_duplicate": 0, "dropped_cap": 0, "transitions": 0, "total_motion": 0.0, "segments": 0}
    if not probes:
        return [], stats
    # "blurry" is judged against the neighbouring stretch of video (about +-2 s), not the whole clip: a plain bathroom next to a
    # richly textured living room must not be thrown away just because its sharpness score is lower
    blurs = np.array([p["blur"] for p in probes])
    half = max(4, int(round(2.0 * config.FRAME_PROBE_FPS)))
    for k, p in enumerate(probes):
        p["blur_min"] = max(blur_abs_min, 0.4 * float(np.median(blurs[max(0, k - half):k + half + 1])))
    chosen, segment, acc = [], [probes[0]], 0.0
    probes[0]["motion"] = 0.0
    probes[0]["cut_before"] = False

    def close(seg, cut_after=False, mark_transition=False):
        stats["segments"] += 1
        sharp = [p for p in seg if p["blur"] >= p["blur_min"]]
        if not sharp:
            return None
        best = max(sharp, key=lambda p: p["blur"])
        if chosen and float(np.mean(cv2.absdiff(best["thumb"], chosen[-1]["thumb"]))) < dup_diff and not mark_transition:
            return None
        best = dict(best)
        if mark_transition:
            best["transition"] = True
        chosen.append(best)
        return best

    for prev, cur in zip(probes, probes[1:]):
        shift, diff, response = _shift_and_diff(prev["thumb"], cur["thumb"])
        # a cut: the picture changed completely (large grey change), or it changed a lot AND no translation explains it
        # (phase-correlation peak collapses). A false positive only keeps one extra frame on each side, which is harmless.
        cut = diff >= cut_diff or (response < 0.12 and diff >= 0.5 * cut_diff)
        m = shift + 0.5 * diff / 255.0
        cur["motion"] = m
        if cut:
            stats["transitions"] += 1
            close(segment)
            segment, acc = [cur], 0.0
            cur["cut_before"] = True
            continue
        stats["total_motion"] += m
        segment.append(cur)
        acc += m
        span = cur["t"] - segment[0]["t"]
        if (acc >= motion_target and span >= min_gap) or span >= max_gap:
            if acc < 0.25 * motion_target and span >= max_gap and chosen:
                pass                                              # camera held still the whole time: the previous kept frame already covers it
            else:
                close(segment)
            segment, acc = [cur], 0.0
    close(segment)
    # a frame that starts a new shot after a cut is a transition marker
    cut_times = {p["t"] for p in probes if p.get("cut_before")}
    for c in chosen:
        if c["t"] in cut_times:
            c["transition"] = True
    stats["total_motion"] = round(stats["total_motion"], 3)
    # accounting per analysed probe: blurry ones, kept ones, and the rest were redundant (overlapping, held-still or duplicate)
    stats["dropped_blur"] = sum(1 for p in probes if p["blur"] < p["blur_min"])
    stats["dropped_duplicate"] = max(0, len(probes) - len(chosen) - stats["dropped_blur"])
    return chosen, stats


def _extract_adaptive(video_rel: str, out_rel: str, is_360: bool, ctx):
    started = time.time()
    info = probe(video_rel, is_360)
    path = str(config.resolve(video_rel))
    out = config.resolve(out_rel)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "thumbs").mkdir()
    max_side, free_mb = ram_limited_side(is_360)
    fps = info["fps"]
    probe_step = max(1, round(fps / max(config.FRAME_PROBE_FPS, 0.5)))
    total = max(info["frame_count"], 1)
    ctx.update("frames", 2, f"Measuring camera motion every {probe_step}th frame (about {fps / probe_step:.1f} probes/s), "
                            f"longest side {max_side}px, free RAM {free_mb if free_mb is not None else 'unknown'} MB")

    # pass 1: decode sequentially, keep only tiny grey thumbnails and a sharpness score per probe
    cap = cv2.VideoCapture(path)
    probes, index, last_t = [], -1, 0.0
    while cap.grab():
        index += 1
        if index % probe_step:
            continue
        ctx.check()
        ok, frame = cap.retrieve()
        if not ok:
            continue
        pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0     # real presentation time: correct for variable frame rate video
        t = pos if (pos > 0 or index == 0) and pos >= last_t else index / fps
        last_t = t
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        probes.append({"frame_index": index, "t": round(t, 3), "blur": _blur_score(gray),
                       "thumb": cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)})
        if len(probes) % 20 == 0:
            ctx.update(progress=2 + 5 * index / total)
    cap.release()
    if len(probes) < 2:
        raise PipelineError("The video has too few readable frames to measure camera movement")

    kept, stats = plan_adaptive(probes)
    warnings = []
    if stats["total_motion"] < config.FRAME_STATIC_MIN_MOTION:
        raise PipelineError(f"The camera hardly moves in this video (measured motion {stats['total_motion']:.2f}, need at least "
                            f"{config.FRAME_STATIC_MIN_MOTION}). Structure from motion needs the camera to travel; walk through the space "
                            "instead of filming from one spot.")
    # cap the count evenly, but never drop a transition frame
    if len(kept) > config.FRAME_MAX:
        keep_idx = set(np.linspace(0, len(kept) - 1, config.FRAME_MAX).round().astype(int).tolist())
        keep_idx |= {i for i, c in enumerate(kept) if c.get("transition")}
        thinned = [c for i, c in enumerate(kept) if i in keep_idx]
        stats["dropped_cap"] = len(kept) - len(thinned)
        kept = thinned
    # overlap check: a long hole between kept frames while the camera moves breaks feature matching there
    gaps = [(a["t"], b["t"]) for a, b in zip(kept, kept[1:]) if b["t"] - a["t"] > 2 * config.FRAME_MAX_GAP_SEC]
    if gaps:
        warnings.append(f"{len(gaps)} gap(s) longer than {2 * config.FRAME_MAX_GAP_SEC:.0f}s between kept frames (e.g. {gaps[0][0]:.1f}s to {gaps[0][1]:.1f}s); "
                        "those stretches may not register.")
    if len(kept) < config.MIN_FRAMES:
        raise PipelineError(f"Only {len(kept)} usable frames after adaptive sampling (blurry {stats['dropped_blur']}, duplicate "
                            f"{stats['dropped_duplicate']}); at least {config.MIN_FRAMES} are needed. Record slower, with better light and more camera movement")

    # pass 2: decode again and write only the chosen frames at the RAM-appropriate resolution
    want = {c["frame_index"]: c for c in kept}
    cap = cv2.VideoCapture(path)
    index, written, size = -1, [], None
    while cap.grab() and len(written) < len(want):
        index += 1
        if index not in want:
            continue
        ctx.check()
        ok, frame = cap.retrieve()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if max(h, w) > max_side:
            sc = max_side / max(h, w)
            frame = cv2.resize(frame, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA)
        size = [frame.shape[1], frame.shape[0]]
        c = want[index]
        c["file"] = f"f_{index:06d}.jpg"
        cv2.imwrite(str(out / c["file"]), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        written.append(c)
        ctx.update(progress=7 + 3 * len(written) / max(1, len(want)))
    cap.release()
    kept = [c for c in kept if "file" in c]
    if len(kept) < config.MIN_FRAMES:
        raise PipelineError(f"Only {len(kept)} chosen frames could be re-read from the video (need {config.MIN_FRAMES}); the file may be damaged")
    duration = info["duration_sec"] or (probes[-1]["t"] - probes[0]["t"])
    drops = {k: stats[k] for k in ("dropped_blur", "dropped_duplicate", "dropped_cap")}
    summary = _write_outputs(out, out_rel, kept, probes, drops, info, is_360, ctx, {
        "sampling": "adaptive", "warnings": warnings, "transitions": stats["transitions"],
        "motion": {"total": stats["total_motion"], "segments": stats["segments"], "target_per_frame": config.FRAME_MOTION_TARGET},
        "extraction_seconds": round(time.time() - started, 2),
        "settings": {"frame_step": probe_step, "probe_fps": round(fps / probe_step, 2),
                     "effective_fps": round(len(kept) / duration, 2) if duration else None, "max_side_px": max_side,
                     "free_ram_mb_at_start": free_mb, "min_frames_required": config.MIN_FRAMES}})
    summary["resolution"]["extracted"] = size
    (out / "frames.json").write_text(json.dumps({"summary": summary, "frames": json.loads((out / "frames.json").read_text())["frames"]}))
    return summary
