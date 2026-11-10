"""
CPU-only incremental structure-from-motion built on OpenCV and SciPy. Used when COLMAP is not installed.

Pipeline: SIFT features -> sequential-window matching with ratio test and RANSAC -> focal length self-calibration
(equal singular values of the essential matrix) -> two-view initialisation -> PnP registration of further frames with
triangulation of new points -> sparse bundle adjustment (SciPy).

Honest limits: flat (pinhole) video only, no lens distortion model, no loop closure, matching only inside a window of
neighbouring frames, and the scale of the result is arbitrary. COLMAP is more accurate and is preferred when present.
"""
import json
import logging
import math
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

from . import config
from .errors import PipelineError

log = logging.getLogger("sfm")

MIN_PAIR_INLIERS = 30
MIN_PNP_INLIERS = 12
BA_MAX_POINTS = 2500


def cpu_smoke_test():
    """Exercise CPU feature matching and the SciPy optimiser used by the SfM fallback."""
    rng = np.random.default_rng(4)
    image = np.zeros((192, 256), dtype=np.uint8)
    for _ in range(160):
        x, y = rng.integers(8, 248), rng.integers(8, 184)
        cv2.circle(image, (int(x), int(y)), int(rng.integers(2, 6)), int(rng.integers(80, 255)), -1)
    moved = cv2.warpAffine(image, np.float32([[1, 0, 5], [0, 1, 2]]), (256, 192))
    detector = cv2.SIFT_create(nfeatures=400)
    key_a, desc_a = detector.detectAndCompute(image, None)
    key_b, desc_b = detector.detectAndCompute(moved, None)
    if desc_a is None or desc_b is None:
        return False
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(desc_a, desc_b, k=2)
    good = [a for pair in matches if len(pair) == 2 for a, b in [pair] if a.distance < 0.75 * b.distance]
    if len(key_a) < 8 or len(key_b) < 8 or len(good) < 8:
        return False
    solved = least_squares(lambda x: x - 1.0, np.array([0.0]))
    return bool(solved.success and np.isfinite(solved.x).all())


# ----------------------------------------------------------------------------------------------------------------------
# features and matching
# ----------------------------------------------------------------------------------------------------------------------
def _load_features(frames_dir: Path, frames, ctx):
    sift = cv2.SIFT_create(nfeatures=config.SFM_FEATURES)
    feats, sizes = [], []
    for n, fr in enumerate(frames):
        ctx.check()
        img = cv2.imread(str(frames_dir / fr["name"]))
        if img is None:
            raise PipelineError(f"Frame {fr['name']} could not be read")
        h0, w0 = img.shape[:2]
        s = min(1.0, config.SFM_MAX_SIDE / max(h0, w0))
        work = cv2.resize(img, (int(round(w0 * s)), int(round(h0 * s))), interpolation=cv2.INTER_AREA) if s < 1 else img
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        kps, desc = sift.detectAndCompute(gray, None)
        if desc is None or len(kps) < 50:
            feats.append(None)
            sizes.append((w0, h0, work.shape[1], work.shape[0]))
            continue
        desc = desc / (np.abs(desc).sum(axis=1, keepdims=True) + 1e-7)  # RootSIFT
        desc = np.sqrt(desc).astype(np.float32)
        xy = np.array([k.pt for k in kps], np.float32)
        colours = work[np.clip(xy[:, 1].astype(int), 0, work.shape[0] - 1), np.clip(xy[:, 0].astype(int), 0, work.shape[1] - 1)][:, ::-1]
        feats.append({"xy": xy, "desc": desc, "rgb": colours.copy()})
        sizes.append((w0, h0, work.shape[1], work.shape[0]))
        ctx.update(progress=12 + 10 * (n + 1) / len(frames), message=f"Features {n + 1}/{len(frames)}: {len(kps)} keypoints" if n % 10 == 0 else None)
    return feats, sizes


def _match_pair(fa, fb):
    flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=48))
    knn = flann.knnMatch(fa["desc"], fb["desc"], k=2)
    best = {}
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.8 * n.distance and (m.trainIdx not in best or m.distance < best[m.trainIdx].distance):
            best[m.trainIdx] = m
    if len(best) < MIN_PAIR_INLIERS:
        return None
    ia = np.array([m.queryIdx for m in best.values()])
    ib = np.array([m.trainIdx for m in best.values()])
    pa, pb = fa["xy"][ia], fb["xy"][ib]
    try:
        F, mask = cv2.findFundamentalMat(pa, pb, cv2.USAC_MAGSAC, 1.0, 0.999, 5000)
    except cv2.error:  # MAGSAC can fail on degenerate point sets; treat the pair as unmatched
        return None
    if F is None or mask is None or F.shape != (3, 3):
        return None
    mask = mask.ravel().astype(bool)
    if mask.sum() < MIN_PAIR_INLIERS:
        return None
    return {"ia": ia[mask], "ib": ib[mask], "F": F}


def _match_all(feats, ctx):
    pairs = {}
    n = len(feats)
    total = sum(min(config.SFM_MATCH_WINDOW, n - 1 - i) for i in range(n))
    done = 0
    for i in range(n):
        for j in range(i + 1, min(n, i + 1 + config.SFM_MATCH_WINDOW)):
            ctx.check()
            done += 1
            if feats[i] is None or feats[j] is None:
                continue
            res = _match_pair(feats[i], feats[j])
            if res is not None:
                pairs[(i, j)] = res
        ctx.update(progress=22 + 18 * done / max(total, 1), message=f"Matched {done}/{total} frame pairs" if done % 40 == 0 else None)
    return pairs


# ----------------------------------------------------------------------------------------------------------------------
# calibration
# ----------------------------------------------------------------------------------------------------------------------
def _intrinsics_from_file(w0, h0):
    path = config.CAMERA_INTRINSICS_FILE
    if not path or not Path(path).is_file():
        return None
    d = json.loads(Path(path).read_text())
    sx, sy = w0 / d.get("width", w0), h0 / d.get("height", h0)
    return {"fx": d["fx"] * sx, "fy": d["fy"] * sy, "cx": d["cx"] * sx, "cy": d["cy"] * sy}


def self_calibrate(pairs, w, h):
    """
    Focal length from the fundamental matrices of verified pairs. For the right K, E = K^T F K has two equal singular
    values, so we pick the focal that minimises (s1 - s2) / (s1 + s2) over the best-supported pairs.
    Returns (focal_in_working_pixels, cost, quality) where quality is 'good', 'weak' or 'default'.
    """
    ranked = sorted(pairs.items(), key=lambda kv: -len(kv[1]["ia"]))[:14]
    side = max(w, h)
    if not ranked:
        return 0.9 * side, None, "default"

    def cost(f):
        K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
        vals = []
        for _, p in ranked:
            s = np.linalg.svd(K.T @ p["F"] @ K, compute_uv=False)
            vals.append((s[0] - s[1]) / (s[0] + s[1] + 1e-12))
        return float(np.median(vals))

    grid = side * np.exp(np.linspace(math.log(0.45), math.log(2.2), 60))
    costs = [cost(f) for f in grid]
    k = int(np.argmin(costs))
    fine = np.linspace(grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)], 40)
    fine_costs = [cost(f) for f in fine]
    best = float(fine[int(np.argmin(fine_costs))])
    best_cost = min(fine_costs)
    at_edge = k in (0, len(grid) - 1)
    spread = max(costs) - min(costs)
    quality = "good" if (not at_edge and best_cost < 0.08 and spread > 0.01) else "weak"
    if quality == "weak":
        log.warning("focal self-calibration is weak (cost %.3f at edge=%s)", best_cost, at_edge)
        best = 0.9 * side if at_edge else best
    return best, best_cost, quality


def calibrate_chessboard(image_paths, pattern=(9, 6), square_mm=25.0):
    """Classic OpenCV chessboard calibration. Returns a dict that scripts/calibrate_camera.py writes to CAMERA_INTRINSICS_FILE."""
    objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square_mm
    obj, img, size = [], [], None
    for p in image_paths:
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        size = g.shape[::-1]
        ok, corners = cv2.findChessboardCorners(g, pattern)
        if ok:
            corners = cv2.cornerSubPix(g, corners, (11, 11), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
            obj.append(objp)
            img.append(corners)
    if len(obj) < 8:
        raise PipelineError(f"Chessboard found in only {len(obj)} images; at least 8 views are needed")
    rms, K, dist, _, _ = cv2.calibrateCamera(obj, img, size, None, None)
    return {"fx": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]), "cy": float(K[1, 2]),
            "width": size[0], "height": size[1], "rms_reprojection_px": float(rms), "distortion": dist.ravel().tolist()}


# ----------------------------------------------------------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------------------------------------------------------
def _rotate(points, rvec):
    theta = np.linalg.norm(rvec, axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(theta > 1e-12, rvec / np.maximum(theta, 1e-12), 0.0)
    cos, sin = np.cos(theta), np.sin(theta)
    return points * cos + np.cross(k, points) * sin + k * (k * points).sum(1, keepdims=True) * (1 - cos)


def _proj_matrix(K, R, t):
    return K @ np.hstack([R, t.reshape(3, 1)])


def _centre(R, t):
    return -R.T @ t


def _angle_deg(c1, c2, X):
    a, b = X - c1, X - c2
    cosang = (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-12)
    return np.degrees(np.arccos(np.clip(cosang, -1, 1)))


def _reproj_err(K, R, t, X, uv):
    Xc = X @ R.T + t
    z = np.where(Xc[:, 2] > 1e-9, Xc[:, 2], np.nan)
    proj = (Xc[:, :2] / z[:, None]) * np.array([K[0, 0], K[1, 1]]) + np.array([K[0, 2], K[1, 2]])
    return np.linalg.norm(proj - uv, axis=1), Xc[:, 2]


# ----------------------------------------------------------------------------------------------------------------------
# reconstruction state
# ----------------------------------------------------------------------------------------------------------------------
class _Model:
    def __init__(self, feats, pairs, K):
        self.feats, self.pairs, self.K = feats, pairs, K
        self.poses = {}                       # image -> (R, t) world -> camera
        self.X, self.rgb = [], []             # point coordinates and colours
        self.obs = []                         # per point: {image: keypoint index}
        self.kp2pt = {i: {} for i in range(len(feats))}

    def pair_matches(self, i, j):
        """(idx_in_i, idx_in_j) for a pair stored with i < j, flipped as needed."""
        if i < j:
            p = self.pairs.get((i, j))
            return (p["ia"], p["ib"]) if p else (None, None)
        p = self.pairs.get((j, i))
        return (p["ib"], p["ia"]) if p else (None, None)

    def add_point(self, X, rgb, observations):
        pid = len(self.X)
        self.X.append(X)
        self.rgb.append(rgb)
        self.obs.append(dict(observations))
        for img, kp in observations.items():
            self.kp2pt[img][kp] = pid
        return pid

    def triangulate_pair(self, a, b, min_angle=1.5, max_err=2.0):
        """New points from matches between registered images a and b that do not have a 3D point yet."""
        ia, ib = self.pair_matches(a, b)
        if ia is None:
            return 0
        fresh = np.array([(self.kp2pt[a].get(x) is None and self.kp2pt[b].get(y) is None) for x, y in zip(ia, ib)], bool)
        if not fresh.any():
            return 0
        ia, ib = ia[fresh], ib[fresh]
        pa, pb = self.feats[a]["xy"][ia], self.feats[b]["xy"][ib]
        Ra, ta = self.poses[a]
        Rb, tb = self.poses[b]
        Xh = cv2.triangulatePoints(_proj_matrix(self.K, Ra, ta), _proj_matrix(self.K, Rb, tb), pa.T.astype(np.float64), pb.T.astype(np.float64))
        X = (Xh[:3] / Xh[3]).T
        ea, za = _reproj_err(self.K, Ra, ta, X, pa)
        eb, zb = _reproj_err(self.K, Rb, tb, X, pb)
        ang = _angle_deg(_centre(Ra, ta), _centre(Rb, tb), X)
        ok = (za > 0) & (zb > 0) & (ea < max_err) & (eb < max_err) & (ang > min_angle) & np.isfinite(ea) & np.isfinite(eb)
        for x, y, xa, rgb in zip(ia[ok], ib[ok], X[ok], self.feats[a]["rgb"][ia[ok]]):
            self.add_point(xa, rgb, {a: int(x), b: int(y)})
        return int(ok.sum())

    def extend_tracks(self, new_img, max_err=3.0):
        """Attach the new image's keypoints to existing points seen by already registered neighbours."""
        R, t = self.poses[new_img]
        added = 0
        for m in self.poses:
            if m == new_img:
                continue
            ia, im = self.pair_matches(new_img, m)
            if ia is None:
                continue
            for kn, km in zip(ia, im):
                pid = self.kp2pt[m].get(int(km))
                if pid is None or new_img in self.obs[pid] or self.kp2pt[new_img].get(int(kn)) is not None:
                    continue
                err, z = _reproj_err(self.K, R, t, np.array([self.X[pid]]), self.feats[new_img]["xy"][[kn]])
                if z[0] > 0 and err[0] < max_err:
                    self.obs[pid][new_img] = int(kn)
                    self.kp2pt[new_img][int(kn)] = pid
                    added += 1
        return added


def _initialise(model, w, h, ctx):
    """Pick the pair with many matches and real parallax, recover its relative pose and triangulate."""
    K = model.K
    candidates = sorted(model.pairs.items(), key=lambda kv: -len(kv[1]["ia"]))[:25]
    best = None
    for (i, j), p in candidates:
        ctx.check()
        pa, pb = model.feats[i]["xy"][p["ia"]], model.feats[j]["xy"][p["ib"]]
        try:
            E, mask = cv2.findEssentialMat(pa, pb, K, cv2.RANSAC, 0.999, 1.0)
        except cv2.error:
            continue
        if E is None or E.shape != (3, 3):
            continue
        n, R, t, mask2 = cv2.recoverPose(E, pa, pb, K, mask=mask)
        if n < 40:
            continue
        H, hmask = cv2.findHomography(pa, pb, cv2.RANSAC, 2.0)
        h_ratio = float(hmask.sum()) / len(pa) if hmask is not None else 1.0
        Xh = cv2.triangulatePoints(_proj_matrix(K, np.eye(3), np.zeros(3)), _proj_matrix(K, R, t.ravel()),
                                   pa[mask2.ravel() > 0].T.astype(np.float64), pb[mask2.ravel() > 0].T.astype(np.float64))
        X = (Xh[:3] / Xh[3]).T
        ang = float(np.median(_angle_deg(np.zeros(3), _centre(R, t.ravel()), X)))
        score = n * min(ang, 10.0) * (1.0 - 0.5 * h_ratio)
        if ang >= 1.0 and (best is None or score > best[0]):
            best = (score, i, j, R, t.ravel(), n, ang, h_ratio)
    if best is None:
        raise PipelineError("Could not initialise the reconstruction: no pair of frames has both enough matches and enough camera movement. "
                            "Move the camera sideways while filming (not just rotating in place) and keep textured surfaces in view.", 422)
    _, i, j, R, t, n, ang, hr = best
    model.poses[i] = (np.eye(3), np.zeros(3))
    model.poses[j] = (R, t)
    made = model.triangulate_pair(i, j, min_angle=1.0)
    ctx.update(message=f"Initialised from frames {i} and {j}: {made} points, median triangulation angle {ang:.1f} deg")
    if made < 30:
        raise PipelineError(f"Initial pair produced only {made} reliable points; the footage has too little parallax or texture.", 422)
    return i, j


def _register_next(model, ctx):
    """Register the unregistered frame with the most 2D-3D correspondences. Returns its index or None."""
    best = None
    for k in range(len(model.feats)):
        if k in model.poses or model.feats[k] is None:
            continue
        corr = {}
        for m in model.poses:
            ik, im = model.pair_matches(k, m)
            if ik is None:
                continue
            for a, b in zip(ik, im):
                pid = model.kp2pt[m].get(int(b))
                if pid is not None and int(a) not in corr:
                    corr[int(a)] = pid
        if len(corr) >= MIN_PNP_INLIERS * 2 and (best is None or len(corr) > len(best[1])):
            best = (k, corr)
    if best is None:
        return None
    k, corr = best
    kps = np.array(list(corr.keys()))
    pids = np.array(list(corr.values()))
    X = np.array([model.X[p] for p in pids], np.float64)
    uv = model.feats[k]["xy"][kps].astype(np.float64)
    ok, rvec, tvec, inl = cv2.solvePnPRansac(X, uv, model.K, None, iterationsCount=600, reprojectionError=4.0,
                                              confidence=0.999, flags=cv2.SOLVEPNP_EPNP)
    if not ok or inl is None or len(inl) < MIN_PNP_INLIERS:
        model.feats[k] = None  # cannot be placed; do not retry it forever
        ctx.log(f"Frame {k} could not be registered ({0 if inl is None else len(inl)} PnP inliers)")
        return -1
    inl = inl.ravel()
    rvec, tvec = cv2.solvePnPRefineLM(X[inl], uv[inl], model.K, None, rvec, tvec)
    R = cv2.Rodrigues(rvec)[0]
    model.poses[k] = (R, tvec.ravel())
    for a, pid in zip(kps[inl], pids[inl]):
        if k not in model.obs[pid]:
            model.obs[pid][k] = int(a)
            model.kp2pt[k][int(a)] = int(pid)
    for m in list(model.poses):
        if m != k:
            model.triangulate_pair(k, m)
    return k


# ----------------------------------------------------------------------------------------------------------------------
# bundle adjustment
# ----------------------------------------------------------------------------------------------------------------------
def _bundle_adjust(model, ctx, max_nfev=25):
    """Refine camera poses and a well-observed subset of points; the focal length stays fixed."""
    images = sorted(model.poses)
    if len(images) < 3:
        return None
    index = {img: n for n, img in enumerate(images)}
    multi = [p for p in range(len(model.X)) if len(model.obs[p]) >= 3]
    if len(multi) < 20:
        multi = [p for p in range(len(model.X)) if len(model.obs[p]) >= 2]
    rng = np.random.default_rng(0)
    if len(multi) > BA_MAX_POINTS:
        multi = list(rng.choice(multi, BA_MAX_POINTS, replace=False))
    pid_index = {p: n for n, p in enumerate(multi)}
    cam_idx, pt_idx, uv = [], [], []
    for p in multi:
        for img, kp in model.obs[p].items():
            if img in index:
                cam_idx.append(index[img])
                pt_idx.append(pid_index[p])
                uv.append(model.feats[img]["xy"][kp])
    cam_idx, pt_idx, uv = np.array(cam_idx), np.array(pt_idx), np.array(uv, np.float64)
    cams0 = np.array([np.concatenate([cv2.Rodrigues(model.poses[i][0])[0].ravel(), model.poses[i][1]]) for i in images])
    pts0 = np.array([model.X[p] for p in multi])
    n_cam, n_pt = len(images), len(multi)
    fx, fy, cx, cy = model.K[0, 0], model.K[1, 1], model.K[0, 2], model.K[1, 2]

    def unpack(x):
        cams = np.vstack([cams0[:1], x[:(n_cam - 1) * 6].reshape(-1, 6)])  # camera 0 is the fixed reference
        return cams, x[(n_cam - 1) * 6:].reshape(-1, 3)

    def residuals(x):
        cams, pts = unpack(x)
        Pc = _rotate(pts[pt_idx], cams[cam_idx, :3]) + cams[cam_idx, 3:]
        z = np.where(Pc[:, 2] > 1e-6, Pc[:, 2], 1e-6)
        pred = np.stack([fx * Pc[:, 0] / z + cx, fy * Pc[:, 1] / z + cy], 1)
        return (pred - uv).ravel()

    m = 2 * len(cam_idx)
    n = (n_cam - 1) * 6 + 3 * n_pt
    A = lil_matrix((m, n), dtype=int)
    rows = np.arange(len(cam_idx))
    for s in range(2):
        for c in range(6):
            sel = cam_idx > 0
            A[2 * rows[sel] + s, (cam_idx[sel] - 1) * 6 + c] = 1
        for c in range(3):
            A[2 * rows + s, (n_cam - 1) * 6 + 3 * pt_idx + c] = 1
    x0 = np.concatenate([cams0[1:].ravel(), pts0.ravel()])
    before = float(np.sqrt(np.mean(residuals(x0) ** 2)))
    sol = least_squares(residuals, x0, jac_sparsity=A, method="trf", loss="huber", f_scale=1.5, x_scale="jac",
                        max_nfev=max_nfev, verbose=0)
    after = float(np.sqrt(np.mean(residuals(sol.x) ** 2)))
    if after >= before:
        return {"rms_before": before, "rms_after": after, "applied": False}
    cams, pts = unpack(sol.x)
    for n_i, img in enumerate(images):
        model.poses[img] = (cv2.Rodrigues(cams[n_i, :3])[0], cams[n_i, 3:].copy())
    for n_p, p in enumerate(multi):
        model.X[p] = pts[n_p]
    # points outside the optimised subset: re-triangulate from the refined cameras
    inside = set(multi)
    for p in range(len(model.X)):
        if p not in inside:
            _retriangulate(model, p)
    ctx.log(f"Bundle adjustment: RMS reprojection {before:.2f}px -> {after:.2f}px "
            f"({n_cam} cameras, {n_pt} points, {len(cam_idx)} observations)")
    return {"rms_before": before, "rms_after": after, "applied": True}


def _retriangulate(model, pid):
    """Linear (DLT) triangulation of one point from all its observations."""
    rows = []
    for img, kp in model.obs[pid].items():
        if img not in model.poses:
            continue
        R, t = model.poses[img]
        P = _proj_matrix(model.K, R, t)
        u, v = model.feats[img]["xy"][kp]
        rows.append(u * P[2] - P[0])
        rows.append(v * P[2] - P[1])
    if len(rows) < 4:
        return
    _, _, vt = np.linalg.svd(np.array(rows))
    if abs(vt[-1][3]) > 1e-12:
        model.X[pid] = vt[-1][:3] / vt[-1][3]


# ----------------------------------------------------------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------------------------------------------------------
def run(frames_dir: Path, frames, ctx):
    """
    Returns a dict with cams, poses, points, colors in the same shapes the COLMAP parser produces, plus a 'meta' block.
    Raises PipelineError with a specific reason when the footage cannot be reconstructed.
    """
    if len(frames) > config.SFM_MAX_IMAGES:
        pick = np.linspace(0, len(frames) - 1, config.SFM_MAX_IMAGES).round().astype(int)
        frames = [frames[i] for i in sorted(set(pick.tolist()))]
        ctx.log(f"Using {len(frames)} evenly spaced frames (SFM_MAX_IMAGES={config.SFM_MAX_IMAGES})")
    ctx.update("sfm", 12, f"OpenCV structure-from-motion on {len(frames)} frames")

    feats, sizes = _load_features(frames_dir, frames, ctx)
    usable = sum(f is not None for f in feats)
    if usable < 6:
        raise PipelineError(f"Only {usable} frames have enough image features; the footage is too blank or too dark.", 422)
    w0, h0, ww, wh = sizes[next(i for i, f in enumerate(feats) if f is not None)]
    pairs = _match_all(feats, ctx)
    if len(pairs) < 5:
        raise PipelineError(f"Only {len(pairs)} frame pairs could be matched; consecutive frames do not overlap enough. "
                            "Film slower and keep textured objects in view.", 422)

    ctx.update("sfm", 41, "Calibrating the camera")
    given = _intrinsics_from_file(ww, wh)
    if given:
        f_work, cost, quality, source = given["fx"], None, "good", "calibration file"
        cx_w, cy_w = given["cx"], given["cy"]
    else:
        f_work, cost, quality, source = *self_calibrate(pairs, ww, wh)[:3], "self-calibration"
        cx_w, cy_w = ww / 2, wh / 2
    K = np.array([[f_work, 0, cx_w], [0, f_work, cy_w], [0, 0, 1]], np.float64)
    ctx.log(f"Focal length {f_work:.1f}px at {ww}x{wh} ({source}, quality {quality}"
            + (f", cost {cost:.3f}" if cost is not None else "") + ")")

    model = _Model(feats, pairs, K)
    ctx.update("sfm", 44, "Initialising from the best frame pair")
    _initialise(model, ww, wh, ctx)

    registered_since_ba, ba_runs, last_ba = 0, 0, None
    total = usable
    while True:
        ctx.check()
        k = _register_next(model, ctx)
        if k is None:
            break
        if k < 0:
            continue
        registered_since_ba += 1
        ctx.update(progress=44 + 20 * len(model.poses) / total, message=f"Registered frame {k} ({len(model.poses)}/{total}), {len(model.X)} points" if len(model.poses) % 5 == 0 else None)
        if registered_since_ba >= 4:
            last_ba = _bundle_adjust(model, ctx) or last_ba
            ba_runs += 1
            registered_since_ba = 0
    last_ba = _bundle_adjust(model, ctx, max_nfev=40) or last_ba
    ba_runs += 1

    # drop unreliable points
    X = np.array(model.X).reshape(-1, 3)
    keep_pts, keep_rgb = [], []
    kept_pid = []                                          # row in keep_pts -> model point id
    errs_all = []
    for pid in range(len(X)):
        obs = {img: kp for img, kp in model.obs[pid].items() if img in model.poses}
        if len(obs) < 2:
            continue
        errs = []
        depth_ok = True
        for img, kp in obs.items():
            R, t = model.poses[img]
            e, z = _reproj_err(K, R, t, X[pid:pid + 1], feats[img]["xy"][[kp]])
            errs.append(e[0])
            depth_ok &= bool(z[0] > 0)
        if depth_ok and np.nanmean(errs) < 2.0:
            keep_pts.append(X[pid])
            kept_pid.append(pid)
            keep_rgb.append(model.rgb[pid])
            errs_all.append(float(np.nanmean(errs)))
    registered = sorted(model.poses)
    if len(registered) < 6 or len(keep_pts) < 30:
        raise PipelineError(f"OpenCV SfM registered only {len(registered)} of {len(frames)} frames with {len(keep_pts)} reliable points; "
                            "not enough for a model. Film slowly with overlapping views, textured surfaces and good light.", 422)

    sx, sy = w0 / ww, h0 / wh
    cams = {1: {"w": w0, "h": h0, "fx": f_work * sx, "fy": f_work * sy, "cx": cx_w * sx, "cy": cy_w * sy}}
    poses = {}
    for img in registered:
        R, t = model.poses[img]
        poses[frames[img]["name"]] = {"center": _centre(R, t), "axes": R, "camera_id": 1}
    # which landmark (row of the returned point array) each registered image really observed: the proof behind a viewpoint link
    observations = {frames[img]["name"]: [] for img in registered}
    for row, pid in enumerate(kept_pid):
        for img in model.obs[pid]:
            if img in model.poses:
                observations[frames[img]["name"]].append(row)
    meta = {"backend": "opencv-sfm", "frames_used": len(frames), "frames_registered": len(registered),
            "pairs_verified": len(pairs), "focal_px_full_frame": round(f_work * sx, 1), "focal_source": source,
            "focal_quality": quality, "focal_cost": None if cost is None else round(cost, 4),
            "bundle_adjustment_runs": ba_runs, "bundle_adjustment": last_ba,
            "mean_reprojection_px": round(float(np.mean(errs_all)), 3) if errs_all else None,
            "limitations": ["no lens distortion model", "sequential-window matching, no loop closure", "arbitrary scale"]}
    return {"cams": cams, "poses": poses, "points": np.array(keep_pts).reshape(-1, 3),
            "colors": np.array(keep_rgb, np.uint8).reshape(-1, 3), "meta": meta,
            "observations": observations}
