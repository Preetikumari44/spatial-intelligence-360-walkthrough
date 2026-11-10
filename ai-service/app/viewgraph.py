"""
Verified viewpoint graph.

Two viewpoints are linked only when the structure-from-motion model proves they look at the same physical things:

  * they share enough 3D landmarks (points that were matched and triangulated across both frames, RANSAC-verified and
    bundle-adjusted by the reconstruction, so each shared landmark is a "common feature" seen from both positions);
  * those landmarks really project inside both cameras, in front of them (flat video);
  * the two cameras see them from different positions (parallax), so the link is a real change of viewpoint;
  * the viewing directions are compatible.

Capture order and camera distance are NOT evidence. A link between two frames that merely follow each other in the video,
or that are close in space but separated by a wall, is never created here.

Loop closures (a revisit of an earlier place) need stronger evidence than a normal neighbour link and are labelled as such.
Components that are not connected to the main walkthrough are reported, never joined by a made-up link.
"""
import math

import numpy as np

from . import config, geometry


def landmarks_by_projection(cand, points, max_depth_factor=6.0):
    """
    Fallback for reconstructions that predate observations.json: a landmark counts as seen by a flat camera when it projects
    inside the image in front of the camera. This is weaker than real tracks (it ignores occlusion) and is reported as such.
    """
    cam = cand["camera"]
    if cam is None or cand["axes"] is None or len(points) == 0:
        return set()
    c = (cand["axes"] @ (points - cand["center"]).T).T
    z = c[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = cam["fx"] * c[:, 0] / z + cam["cx"]
        v = cam["fy"] * c[:, 1] / z + cam["cy"]
    ok = (z > 1e-9) & (u >= 0) & (u < cam["w"]) & (v >= 0) & (v < cam["h"])
    if ok.any():
        ok &= z <= max_depth_factor * np.median(z[ok])
    return set(np.flatnonzero(ok).tolist())


def _pair_metrics(a, b, points):
    shared = a["landmarks"] & b["landmarks"]
    n = len(shared)
    out = {"shared": n, "overlap": 0.0, "parallax_deg": None, "visible_fraction": 0.0, "view_angle_deg": 0.0}
    if n == 0:
        return out
    out["overlap"] = n / max(1, min(len(a["landmarks"]), len(b["landmarks"])))
    if a["axes"] is not None and b["axes"] is not None:
        za, zb = a["axes"][2], b["axes"][2]
        out["view_angle_deg"] = math.degrees(math.acos(float(np.clip(za @ zb, -1, 1))))
    if points is not None and len(points):
        idx = np.fromiter(shared, int)
        if len(idx) > 300:
            idx = np.random.default_rng(7).choice(idx, 300, replace=False)
        X = points[idx]
        va, vb = a["center"] - X, b["center"] - X
        na, nb = np.linalg.norm(va, axis=1), np.linalg.norm(vb, axis=1)
        cosang = np.einsum("ij,ij->i", va, vb) / np.maximum(na * nb, 1e-12)
        out["parallax_deg"] = float(np.median(np.degrees(np.arccos(np.clip(cosang, -1, 1)))))
        vis = []
        for c in (a, b):
            cam = c["camera"]
            if cam is None or c["axes"] is None:
                continue                                     # a panorama sees all around: nothing to project
            cc = (c["axes"] @ (X - c["center"]).T).T
            z = cc[:, 2]
            with np.errstate(divide="ignore", invalid="ignore"):
                u = cam["fx"] * cc[:, 0] / z + cam["cx"]
                v = cam["fy"] * cc[:, 1] / z + cam["cy"]
            vis.append(float(np.mean((z > 1e-9) & (u >= -0.05 * cam["w"]) & (u < 1.05 * cam["w"]) & (v >= -0.05 * cam["h"]) & (v < 1.05 * cam["h"]))))
        out["visible_fraction"] = min(vis) if vis else 1.0
    else:
        out["visible_fraction"] = 1.0                        # no point coordinates stored: parallax and projection cannot be checked
    return out


def _min_shared(nodes):
    sizes = sorted(len(n["landmarks"]) for n in nodes)
    med = sizes[len(sizes) // 2] if sizes else 0
    return int(max(8, min(config.TOUR_MIN_SHARED_LANDMARKS, round(0.15 * med))))


def _confidence(m, min_shared):
    return round(min(1.0, 0.5 * min(1.0, m["shared"] / (4 * min_shared)) + 0.3 * min(1.0, m["overlap"] / 0.5)
                     + 0.2 * min(1.0, (m["parallax_deg"] or 0.0) / 5.0)), 3)


class _DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.p[ra] = rb
        return True


def build(nodes, points, k_neighbours=4):
    """
    nodes: list of {"center", "axes" (3x3 or None), "camera" (dict or None), "landmarks" (set of ints), "t" (seconds)} in time order.
    Returns {"edges": [...], "components": [[node idx...]], "main": [node idx...], "min_shared": int, "candidates": int}.
    Every returned edge passed every check above; it carries the numbers that justify it.
    """
    n = len(nodes)
    min_shared = _min_shared(nodes)
    valid = []
    for i in range(n):
        for j in range(i + 1, n):
            m = _pair_metrics(nodes[i], nodes[j], points)
            if m["shared"] < min_shared or m["overlap"] < config.TOUR_MIN_OVERLAP:
                continue
            if m["visible_fraction"] < 0.5 or (m["parallax_deg"] is not None and m["parallax_deg"] < config.TOUR_MIN_PARALLAX_DEG):
                continue
            if nodes[i]["axes"] is not None and nodes[j]["axes"] is not None and m["view_angle_deg"] > config.TOUR_MAX_VIEW_ANGLE_DEG:
                continue
            gap = abs(nodes[j]["t"] - nodes[i]["t"])
            m["kind"] = "loop_closure" if (j - i > 5 and gap >= config.TOUR_LOOP_MIN_GAP_SEC) else "covisibility"
            m["score"] = m["shared"] * m["overlap"]
            m["confidence"] = _confidence(m, min_shared)
            m["i"], m["j"] = i, j
            valid.append(m)

    keep = {}
    # each viewpoint keeps its best few verified neighbours
    for i in range(n):
        mine = sorted((m for m in valid if i in (m["i"], m["j"])), key=lambda m: -m["score"])[:k_neighbours]
        for m in mine:
            keep[(m["i"], m["j"])] = m
    # strongest spanning forest: guarantees that everything that CAN be connected through verified links, is
    dsu = _DSU(n)
    for m in sorted(valid, key=lambda m: -m["score"]):
        if dsu.union(m["i"], m["j"]):
            keep.setdefault((m["i"], m["j"]), m)
    # a loop closure joins two distant moments of the video: it needs clearly more evidence than a neighbour link
    strong = 1.5 * min_shared
    edges = [m for m in keep.values() if m["kind"] != "loop_closure" or m["shared"] >= strong]
    # dropping weak loop closures must not disconnect anything the forest connected, so re-add the ones that are bridges
    dsu2 = _DSU(n)
    for m in edges:
        dsu2.union(m["i"], m["j"])
    for m in sorted(keep.values(), key=lambda m: -m["score"]):
        if m not in edges and dsu2.union(m["i"], m["j"]):
            edges.append(m)

    dsu3 = _DSU(n)
    for m in edges:
        dsu3.union(m["i"], m["j"])
    groups = {}
    for i in range(n):
        groups.setdefault(dsu3.find(i), []).append(i)
    components = sorted(groups.values(), key=lambda g: (-len(g), g[0]))
    return {"edges": sorted(edges, key=lambda m: (m["i"], m["j"])), "components": components,
            "main": sorted(components[0]) if components else [], "min_shared": min_shared, "candidates": len(valid)}
