"""
Pipeline A: every extracted video frame -> viewpoint -> verified navigation links -> validation.   NO COLMAP, NO 3D reconstruction.

Everything here comes from the frames that frame extraction wrote (real pixels, real timestamps). Nothing is invented:
  * a viewpoint is one real frame; its label is neutral ("Viewpoint 01"); areas are "Area 1..n" (a new area starts at a detected
    cut or a strong appearance change). Room TYPES (kitchen, bedroom...) are not guessed: no classifier is bundled, so they are not claimed.
  * a link exists only when two viewpoints are PROVEN to see the same physical features: ORB matches (Lowe ratio test) that survive RANSAC
    estimation of the essential matrix (with a cheirality check on the recovered pose) or of a homography (pure rotation / planar scene).
    Every extracted frame is retained as a viewpoint. Where the video cuts or overlap breaks, NO link is made: that stretch is reported as a
    separate segment, and all its viewpoints remain selectable. Nothing is joined because frame numbers follow.
    A REVISIT (a later moment that sees an earlier place) is verified the same way, more strictly.
  * hotspot direction comes from the recovered relative camera pose (translation direction of the essential matrix, approximate focal length);
    image flow is only the fallback when the pose is degenerate. It is approximate and says so. A link that points behind the camera, or whose
    position cannot be estimated, is not drawn in the picture but is listed.
  * flat video is never turned into a panorama. For 360 footage the nodes are panoramas, but without poses the direction of a link is unknown,
    so links are listed (directional=false) instead of being drawn at a made-up yaw.
The result is validated (files readable, every extracted frame represented, hotspots in range, timestamps ordered). If validation fails nothing is published.
"""
import json
import math
from pathlib import Path

import cv2
import numpy as np

from . import config
from .errors import PipelineError

ORB_SIZE = 640
HIST_BINS = (8, 4, 4)
REVISIT_MIN_GAP_SEC = 8.0
GLOBAL_MATCH_CANDIDATES = 6
REMOTE_MATCH_CANDIDATES = 3
MAX_REMOTE_LINKS_PER_VIEWPOINT = 2


def _load(frames_rel):
    meta = json.loads((config.resolve(frames_rel) / "frames.json").read_text())
    frames = meta["frames"]
    if len(frames) < 2:
        raise PipelineError("Fewer than 2 extracted frames: a tour needs at least two viewpoints. Upload a longer or steadier video.", 422)
    return meta.get("summary", {}), frames


def _describe(frames, require_equirectangular=False):
    """One pass over the frames, one image in memory at a time: histogram, ORB features, exposure."""
    orb = cv2.ORB_create(nfeatures=800, fastThreshold=12)
    out = []
    for f in frames:
        img = cv2.imread(str(config.resolve(f["file"])))
        if img is None:
            raise PipelineError(f"Frame {f['name']} cannot be read from storage; frame extraction output is damaged.", 500)
        h, w = img.shape[:2]
        if require_equirectangular and abs(w / h - 2.0) >= 0.05:
            raise PipelineError(
                f"Frame {f['name']} is {w}x{h}; declared 360-degree source frames must remain 2:1 equirectangular images.",
                422,
            )
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, list(HIST_BINS), [0, 180, 0, 256, 0, 256])
        hist = cv2.normalize(hist, None, 1.0, 0.0, cv2.NORM_L1).flatten().astype(np.float32)
        s = ORB_SIZE / max(w, h)
        small = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else gray
        kp, des = orb.detectAndCompute(small, None)
        pts = np.array([k.pt for k in kp], np.float32) / (s if s < 1 else 1.0) if kp else np.zeros((0, 2), np.float32)
        mean = float(gray.mean())
        dark = float((gray < 8).mean())
        bright = float((gray > 247).mean())
        flag = "dark" if mean < 40 else "overexposed" if (mean > 215 or bright > 0.35) else None
        out.append({"w": w, "h": h, "hist": hist, "des": des, "pts": pts, "exposure": {"mean_luma": round(mean, 1), "clipped_dark": round(dark, 3),
                    "clipped_bright": round(bright, 3), "flag": flag}, "features": len(kp)})
    return out


def _hdist(a, b):
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


_bf = cv2.BFMatcher(cv2.NORM_HAMMING)


def _match(da, db):
    """Ratio-tested ORB matches. Returns index arrays or None."""
    if da["des"] is None or db["des"] is None or len(da["des"]) < 8 or len(db["des"]) < 8:
        return None
    good = []
    for m in _bf.knnMatch(da["des"], db["des"], k=2):
        if len(m) == 2 and m[0].distance < 0.8 * m[1].distance:
            good.append(m[0])
    if len(good) < 8:
        return None
    return np.array([m.queryIdx for m in good]), np.array([m.trainIdx for m in good])


def _intrinsics(w, h):
    """Approximate pinhole camera for a frame: a calibration file if configured (scripts/calibrate_camera.py), else a typical phone field of view."""
    f, cx, cy = 0.875 * w, w / 2.0, h / 2.0
    if config.CAMERA_INTRINSICS_FILE:
        try:
            d = json.loads(Path(config.CAMERA_INTRINSICS_FILE).read_text())
            k = w / float(d.get("width") or w)
            f, cx, cy = float(d["fx"]) * k, float(d.get("cx", d.get("width", w) / 2.0)) * k, float(d.get("cy", d.get("height", h) / 2.0)) * k
        except (OSError, ValueError, KeyError):
            pass
    return np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]], np.float64)


def _relate(da, db, geometric=True):
    """
    Geometric verification of two frames. Returns a dict with inliers (0 = not verified), matches, ratio and, when the relative pose can be
    recovered, dir_ab: unit direction of B's camera centre in A's camera frame (x right, y down, z forward) and dir_ba for the reverse.
    geometric=False (360 equirectangular frames, where a pinhole model is wrong) verifies with an affine / fundamental fit instead.
    """
    m = _match(da, db)
    res = {"inliers": 0, "matches": 0, "ratio": 0.0, "pose": False}
    if m is None:
        return res
    qa, qb = m
    pa, pb = da["pts"][qa], db["pts"][qb]
    res["matches"] = len(qa)
    A, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=4.0, maxIters=2000, confidence=0.99)
    n_aff = int(inl.sum()) if inl is not None else 0
    res["affine_inliers"] = n_aff
    n_fun = n_ess = n_hom = 0
    if len(qa) >= 12:
        F, fin = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 2.0, 0.99)
        n_fun = int(fin.sum()) if fin is not None else 0
        if geometric and len(qa) >= 8:
            K = _intrinsics(da["w"], da["h"])
            try:
                E, emask = cv2.findEssentialMat(pa, pb, K, method=cv2.RANSAC, prob=0.999, threshold=1.5)
                if E is not None and emask is not None and E.shape[0] >= 3:
                    n_ess, R, t, _ = cv2.recoverPose(E[:3], pa, pb, K, mask=emask.copy())     # inliers in front of both cameras
                    res["essential_inliers"] = int(n_ess)
                    H, hmask = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
                    n_hom = int(hmask.sum()) if hmask is not None else 0
                    res["homography_inliers"] = n_hom
                    # a planar scene or a pure rotation is explained by a homography: then the translation direction is not trustworthy
                    if n_ess >= config.TOUR_VERIFY_INLIERS and n_hom < 0.9 * n_ess:
                        t = t.ravel() / max(np.linalg.norm(t), 1e-12)
                        res["pose"] = True
                        res["dir_ab"] = (-R.T @ t).tolist()                  # B's centre seen from A
                        res["dir_ba"] = t.tolist()                           # A's centre seen from B
            except cv2.error:
                n_ess = n_hom = 0
    if geometric:
        res["inliers"] = int(max(n_ess, n_hom))
    else:
        res["inliers"] = max(n_aff, n_fun)
    res["fundamental_inliers"] = n_fun
    res["ratio"] = round(res["inliers"] / max(1, len(qa)), 3)
    if A is not None and n_aff >= 8:
        sel = pa[inl.ravel().astype(bool)]
        res["scale"] = float(math.hypot(A[0, 0], A[1, 0]))
        res["tx"] = float(A[0, 2]) / da["w"]
        res["ty"] = float(A[1, 2]) / da["h"]
        res["centroid"] = [float(np.clip(sel[:, 0].mean() / da["w"], 0, 1)), float(np.clip(sel[:, 1].mean() / da["h"], 0, 1))]
    return res


def _flip(rel):
    """The same verified pair seen from the other frame (the pose direction is reversed; image-flow terms are recomputed by the caller if needed)."""
    out = {k: v for k, v in rel.items() if k not in ("dir_ab", "dir_ba", "scale", "tx", "ty", "centroid")}
    if rel.get("pose"):
        out["dir_ab"], out["dir_ba"] = rel["dir_ba"], rel["dir_ab"]
    return out


def _connect_all_frames(frames, descs, is_360, ctx=None):
    """Keep every frame and geometrically verify local and appearance-retrieved frame pairs."""
    n = len(frames)
    idx = list(range(n))
    times = [float(f.get("t", i)) for i, f in enumerate(frames)]
    candidates = set()
    for i in range(n):
        for j in range(max(0, i - 2), min(n, i + 3)):
            if i != j:
                candidates.add((min(i, j), max(i, j)))

        # Appearance ranks candidates only; ORB matches plus geometric verification remain the proof of a link.
        ranked = sorted(
            ((_hdist(descs[i]["hist"], descs[j]["hist"]), j) for j in range(n) if j != i),
            key=lambda item: (item[0], item[1]),
        )
        global_added = 0
        remote_added = 0
        for _, j in ranked:
            pair = (min(i, j), max(i, j))
            remote = abs(times[j] - times[i]) >= REVISIT_MIN_GAP_SEC
            if remote:
                if remote_added >= REMOTE_MATCH_CANDIDATES:
                    continue
                remote_added += 1
            elif global_added >= GLOBAL_MATCH_CANDIDATES:
                continue
            else:
                global_added += 1
            candidates.add(pair)

    rels = {}
    ordered_candidates = sorted(candidates)
    total = len(ordered_candidates)
    for number, (i, j) in enumerate(ordered_candidates, 1):
        rels[(i, j)] = _relate(descs[i], descs[j], geometric=not is_360)
        if ctx and number % 32 == 0:
            ctx.update("tour", min(54, 40 + int(14 * number / max(1, total))),
                       f"Verifying candidate viewpoint links ({number}/{total})")

    seg = [0]
    for i in range(1, n):
        adjacent = rels.get((i - 1, i), {})
        seg.append(seg[-1] + int(adjacent.get("inliers", 0) < config.TOUR_VERIFY_INLIERS))
    return idx, seg, rels


def _areas(frames, descs, idx, rels, is_360):
    """Group consecutive viewpoints: a new area starts at a detected cut or when appearance changes sharply AND the frames barely match."""
    area, areas = 0, []
    for k, i in enumerate(idx):
        if k:
            j = idx[k - 1]
            cut = bool(frames[i].get("transition"))
            if not cut and _hdist(descs[j]["hist"], descs[i]["hist"]) > 0.45:
                rel = rels.get((min(i, j), max(i, j)))
                if rel is None:
                    rel = _relate(descs[j], descs[i], geometric=not is_360)
                cut = rel["inliers"] < config.TOUR_VERIFY_INLIERS
            area += 1 if cut else 0
        areas.append(area)
    return areas


def _hotspot_flow(rel, is_360):
    """Return no image hotspot when image correspondences do not locate the destination itself."""
    if is_360:
        return {"visible": False, "bearing": 0.0, "directional": False, "method": "none", "approximate": True,
                "note": "direction unknown without camera poses"}
    return {"visible": False, "bearing": 0.0, "directional": False, "method": "verified-overlap",
            "approximate": False, "note": "destination location is not projected in this 2D viewpoint"}


def _hotspot(rel, is_360, dir_key="dir_ab", wh=None):
    """Only provide direction when estimated; a correspondence centroid is not a doorway or destination location."""
    if is_360:
        return _hotspot_flow(rel, True)
    d = rel.get(dir_key) if rel.get("pose") else None
    if d is None:
        return _hotspot_flow(rel, False)
    dx, dy, dz = d
    bearing = round(math.atan2(dx, dz), 4)
    return {"visible": False, "bearing": bearing, "directional": True, "method": "essential-matrix",
            "approximate": True, "note": "relative direction only; no doorway or destination pixel is verified"}


def _validate(work, nodes, conns, frames_by_name):
    checks = []

    def chk(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
    chk("at least 2 viewpoints", len(nodes) >= 2, f"{len(nodes)} viewpoints")
    missing = [n["frame"] for n in nodes if not config.resolve(n["frame"]).is_file()]
    chk("viewpoint images exist", not missing, f"missing {missing[:3]}" if missing else "")
    missing_t = [n["thumb"] for n in nodes if not config.resolve(n["thumb"]).is_file()]
    chk("thumbnails exist", not missing_t, f"missing {missing_t[:3]}" if missing_t else "")
    ids = {n["id"] for n in nodes}
    chk("connections reference existing viewpoints", all(c["from"] in ids and c["to"] in ids and c["from"] != c["to"] for c in conns))
    bad = [c for c in conns if c["hotspot"].get("visible") and not (0 <= c["hotspot"]["x"] <= 1 and 0 <= c["hotspot"]["y"] <= 1)]
    chk("hotspot coordinates inside the image", not bad, f"{len(bad)} outside" if bad else "")
    ts = [n["time_sec"] for n in nodes]
    chk("timestamps are in capture order", ts == sorted(ts))
    node_frames = [n.get("frame_id") for n in nodes]
    extracted_frames = list(frames_by_name)
    complete = node_frames == extracted_frames and len(set(node_frames)) == len(node_frames)
    chk("every extracted frame is a viewpoint", complete, f"{len(node_frames)} viewpoints for {len(extracted_frames)} extracted frames")
    ok = all(c["ok"] for c in checks)
    return {"passed": ok, "checks": checks}


def _components(n, links):
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in links:
        parent[find(a)] = find(b)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def build(frames_rel: str, work_rel: str, is_360: bool, ctx=None):
    work = config.resolve(work_rel)
    work.mkdir(parents=True, exist_ok=True)
    summary, frames = _load(frames_rel)
    if ctx:
        ctx.update("tour", 40, f"Describing {len(frames)} frames (features, exposure, appearance)")
    descs = _describe(frames, require_equirectangular=is_360)
    idx, seg, rels = _connect_all_frames(frames, descs, is_360, ctx)
    if len(idx) < 2:
        raise PipelineError("Only one usable viewpoint was found. The video needs to move through the space.", 422)
    warnings = []
    geo = not is_360

    # ---- verified links between consecutive viewpoints and later revisits ---------------------------------------------
    raw = []                                                     # (pos_a, pos_b, kind, rel_ab, rel_ba)
    for (a, b), rab in rels.items():
        if (rab["inliers"] < config.TOUR_VERIFY_INLIERS or rab["ratio"] < 0.2) and not config.TOUR_ALLOW_UNVERIFIED_LINKS:
            continue
        rba = _flip(rab)
        if not geo or not rab.get("pose"):
            rba = _relate(descs[idx[b]], descs[idx[a]], geo)     # no pose to reverse: measure the other direction (image-flow hotspot)
        link_kind = "sequence" if b == a + 1 else (
            "revisit" if abs(float(frames[b]["t"]) - float(frames[a]["t"])) >= REVISIT_MIN_GAP_SEC else "visual_match"
        )
        if link_kind == "revisit" and (rab["inliers"] < config.TOUR_REVISIT_INLIERS or rab["ratio"] < 0.35):
            continue
        raw.append((a, b, link_kind, rab, rba))
    if config.TOUR_ALLOW_UNVERIFIED_LINKS:                        # legacy switch: join broken stretches by video order, flagged unverified
        for b in range(1, len(idx)):
            if seg[b] != seg[b - 1]:
                rab, rba = _relate(descs[idx[b - 1]], descs[idx[b]], geo), _relate(descs[idx[b]], descs[idx[b - 1]], geo)
                raw.append((b - 1, b, "sequence", rab, rba))
                warnings.append(f"Link {b:02d}-{b + 1:02d} follows the video order only (TOUR_ALLOW_UNVERIFIED_LINKS=1); the frames do not overlap.")
    revisit = 0
    revisit = sum(1 for a, b, kind, *_ in raw if kind == "revisit")
    # Keep strong non-local alternatives without making a dense, hard-to-navigate web. Candidate verification still
    # considers the full retrieval shortlist; this cap affects presentation, never viewpoint retention.
    local = [edge for edge in raw if edge[1] == edge[0] + 1]
    remote = [edge for edge in raw if edge[1] != edge[0] + 1]
    chosen_remote = set()
    for k in range(len(idx)):
        ranked = sorted(
            (edge for edge in remote if k in edge[:2]),
            key=lambda edge: -(edge[3]["inliers"] * edge[3]["ratio"]),
        )
        chosen_remote.update((edge[0], edge[1]) for edge in ranked[:MAX_REMOTE_LINKS_PER_VIEWPOINT])
    raw = local + [edge for edge in remote if (edge[0], edge[1]) in chosen_remote]
    revisit = sum(1 for _, _, kind, *_ in raw if kind == "revisit")

    # Keep disconnected stretches as viewpoints, but never invent links between them.
    comps = _components(len(idx), [(a, b) for a, b, *_ in raw])
    included = list(range(len(idx)))
    new_of = {old: new for new, old in enumerate(included)}
    if len(comps) > 1:
        warnings.append(
            f"The video contains {len(comps)} separate viewpoint groups with no verified visual link between some groups. "
            "All extracted viewpoints are included; select a viewpoint from the list to open another group."
        )
    kept_idx = [idx[p] for p in included]
    areas = _areas(frames, descs, kept_idx, rels, is_360)

    nodes = []
    for k, i in enumerate(kept_idx):
        f, d = frames[i], descs[i]
        conf = 1.0
        if d["exposure"]["flag"]:
            conf -= 0.3
            warnings.append(f"Viewpoint {k + 1} ({f['t']:.1f}s) is {d['exposure']['flag']}.")
        conf = round(max(0.1, conf * min(1.0, d["features"] / 300)), 2)
        nodes.append({"id": f"n{k}", "seq": k, "label": f"Viewpoint {k + 1:02d}", "frame": f["file"], "thumb": f.get("thumb") or f["file"],
                      "frame_id": f["name"], "video_frame_index": f["frame_index"], "time_sec": f["t"], "panorama": bool(is_360),
                      "position": None, "heading_rad": 0.0, "has_pose": False, "camera": None, "area": f"Area {areas[k] + 1}",
                      "confidence": conf, "exposure": d["exposure"], "features": d["features"], "sharpness": f.get("blur"),
                      "resolution": [d["w"], d["h"]], "validation": "ok"})
    if ctx:
        ctx.update("tour", 62, f"Placing hotspots between {len(nodes)} verified viewpoints")

    conns = []
    for a, b, kind, rab, rba in raw:
        if a not in new_of or b not in new_of:
            continue
        ka, kb = new_of[a], new_of[b]
        for src, dst, rel, key in ((ka, kb, rab, "dir_ab"), (kb, ka, rba, "dir_ab")):
            if (rel["inliers"] < config.TOUR_VERIFY_INLIERS or rel["ratio"] < 0.2) and not config.TOUR_ALLOW_UNVERIFIED_LINKS:
                continue
            wh = (descs[kept_idx[src]]["w"], descs[kept_idx[src]]["h"])
            hs = _hotspot(rel, is_360, key, wh)
            verified = rel["inliers"] >= config.TOUR_VERIFY_INLIERS
            hs.update({"kind": kind, "verified": verified, "inliers": rel["inliers"], "matches": rel.get("matches", 0),
                       "evidence": "essential matrix" if rel.get("pose") else ("homography/affine" if geo else "affine/fundamental")})
            conns.append({"from": f"n{src}", "to": f"n{dst}", "hotspot": hs, "distance": 0.0, "kind": kind, "verified": verified,
                          "inliers": rel["inliers"], "confidence": round(min(1.0, rel["inliers"] / 120.0), 2)})
    if ctx:
        ctx.update("tour", 70, "Validating tour assets")

    times = [n["time_sec"] for n in nodes]
    dur = float(summary.get("duration_sec") or (times[-1] - times[0]) or 0)
    gaps = [[round(a, 2), round(b, 2)] for a, b in zip(times, times[1:]) if b - a > max(2 * config.FRAME_MAX_GAP_SEC, 6.0)]
    if not conns:
        warnings.append("No visual links could be verified between the extracted frames. All viewpoints are still available in the list.")
    warnings.append("No 3D camera positions exist for this tour: navigation follows verified visual overlap; "
                    "there is no floor plan or measurement.")
    warnings.append("360-degree rotation is not available for flat video." if not is_360 else
                    "360 panoramas are linked where their content verifies; hotspot directions need camera poses (advanced 3D).")
    if gaps:
        warnings.append(f"{len(gaps)} stretch(es) of the video have no viewpoint (longest gap {max(b - a for a, b in gaps):.0f}s); that area is not covered.")

    validation = _validate(work, nodes, conns, {f["name"]: f for f in frames})
    unverified = [c for c in conns if not c["verified"]]
    validation["checks"].append({"check": "every link is geometrically verified", "ok": not unverified or config.TOUR_ALLOW_UNVERIFIED_LINKS,
                                 "detail": f"{len(unverified)} unverified" if unverified else ""})
    validation["passed"] = all(c["ok"] for c in validation["checks"])
    seq_total = sum(1 for a, b, k, *_ in raw if k == "sequence" and a in new_of and b in new_of)
    manifest = {
        "mode": "viewpoint", "has_poses": False, "is_360": bool(is_360), "units": None, "extents": None,
        "panorama_coverage": {
            "status": "source_declared_not_content_verified" if is_360 else "not_available",
            "projection": "equirectangular" if is_360 else None,
            "horizontal_degrees": 360 if is_360 else 0,
            "vertical_degrees": 180 if is_360 else 0,
            "asset_method": "original_extracted_video_frame" if is_360 else None,
            "best_candidate_sphere_area_coverage": None,
            "best_candidate_horizon_band_coverage": None,
            "note": (
                "Coverage is inferred from the user-declared 2:1 equirectangular source format; image content and spherical capture were not independently verified. "
                "These are extracted source frames, not stitched panoramas."
                if is_360 else "The source is ordinary video; no 360-degree panorama was generated."
            ),
        },
        "coverage": {"viewpoints": len(nodes), "frames_extracted": len(frames), "source_duration_sec": round(dur, 2),
                     "first_time_sec": times[0], "last_time_sec": times[-1], "sequence_links_verified": sum(1 for c in conns if c["kind"] == "sequence" and c["verified"]) // 2,
                     "sequence_links_total": seq_total, "revisit_links": sum(1 for c in conns if c["kind"] == "revisit") // 2, "gaps_sec": gaps,
                     "areas": len(set(areas)), "exposure_flagged": sum(1 for n in nodes if n["exposure"]["flag"]),
                     "segments_found": len(comps), "viewpoints_left_out": 0},
        "areas": [{"name": f"Area {a + 1}", "viewpoints": [n["id"] for n, ar in zip(nodes, areas) if ar == a]} for a in sorted(set(areas))],
        "floorplan": {"kind": "none", "points": [], "bounds": {"minx": 0, "maxx": 0, "minz": 0, "maxz": 0}, "note": "No camera poses: no floor plan."},
        "graph": {"nodes": nodes, "connections": conns}, "validation": validation, "warnings": warnings,
        "link_evidence": ("essential matrix (RANSAC, cheirality-checked) or homography on ratio-tested ORB matches" if geo
                          else "affine / fundamental fit on ratio-tested ORB matches (equirectangular frames)"),
        "matching": {"candidate_pairs_evaluated": len(rels),
                     "candidate_method": "adjacent temporal frames plus top appearance-ranked pairs per viewpoint; appearance is retrieval only, links require geometric verification"},
        "labels": "neutral (Viewpoint/Area numbers); room types are not guessed",
        "hotspots": "approximate: direction from the recovered relative camera pose (focal length is an estimate), image flow as fallback",
        "source": {"frames_dir": frames_rel, "sampling": summary.get("sampling")},
    }
    (work / "tour_manifest.json").write_text(json.dumps(manifest))
    if not validation["passed"]:
        failed = "; ".join(f"{c['check']} ({c['detail']})" for c in validation["checks"] if not c["ok"])
        raise PipelineError(f"Tour validation failed, nothing was published: {failed}", 500)
    return {"nodes": nodes, "connections": conns, "manifest_path": f"{work_rel}/tour_manifest.json", "points_path": None,
            "validation": validation, "mode": "viewpoint", "warnings": warnings}
