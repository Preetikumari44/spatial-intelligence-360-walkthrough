"""Turns reconstructed camera poses into navigable viewpoints, hotspots and a floor-plan point map."""
import json
import math
from pathlib import Path

import numpy as np

from . import config, geometry, panorama, viewgraph
from .errors import PipelineError

MAX_NODES = max(100, config.FRAME_MAX)
FACE_YAWS = (0, 90, 180, 270)


def _frame_candidates(recon, frames_rel):
    """One candidate per registered frame: position, heading and (for flat video) camera + frame image."""
    imgs = recon["images"]
    cands = []
    for fr in sorted((f for f in recon["frames"] if f["registered"]), key=lambda f: f["frame_index"]):
        if recon["is_360"]:
            faces = [(k, imgs[f"{fr['stem']}__{k}.jpg"]) for k in range(4) if f"{fr['stem']}__{k}.jpg" in imgs]
            center = np.mean([np.array(i["center"]) for _, i in faces], axis=0)
            offsets = [geometry.phi(np.array(i["axes"])[2]) - math.radians(FACE_YAWS[k]) for k, i in faces]
            cands.append({"fr": fr, "center": center, "heading": geometry.circular_mean(offsets),
                          "axes": None, "camera": None})
        else:
            i = imgs[fr["name"]]
            axes = np.array(i["axes"])
            cands.append({"fr": fr, "center": np.array(i["center"]), "heading": geometry.phi(axes[2]),
                          "axes": axes, "camera": recon["cameras"][str(i["camera_id"])]})
    return cands


def _select(cands, d_min):
    kept = []
    for c in cands:
        if not kept:
            kept.append(c)
            continue
        previous = kept[-1]
        moved = np.linalg.norm(c["center"] - previous["center"]) >= d_min
        if c["axes"] is not None and previous["axes"] is not None:
            forward_a, forward_b = c["axes"][2], previous["axes"][2]
            angle = math.degrees(math.acos(float(np.clip(forward_a @ forward_b, -1.0, 1.0))))
        else:
            angle = abs(math.degrees(geometry.wrap(c["heading"] - previous["heading"])))
        if moved or angle >= 15.0:
            kept.append(c)
    return kept


def _choose_nodes(cands, density=1.0):
    """Thin the registered frames by camera distance. density > 1 keeps more viewpoints (used when the first choice is too sparse to link)."""
    centers = np.array([c["center"] for c in cands])
    extent = float(np.linalg.norm(centers.max(axis=0) - centers.min(axis=0)))
    if extent <= 0:
        raise PipelineError("All camera positions coincide; the camera did not move enough to build a tour.", 422)
    d_min = 0.05 * extent / density
    kept = _select(cands, d_min)
    while len(kept) > MAX_NODES:
        d_min *= 1.3
        kept = _select(cands, d_min)
    while len(kept) < 3 and d_min > extent * 1e-3:
        d_min *= 0.5
        kept = _select(cands, d_min)
    if len(kept) < 2:
        raise PipelineError("Not enough distinct camera positions for a tour.", 422)
    return kept, d_min


def hotspot(a, b, points=None):
    """Place flat-view hotspots only on a shared reconstructed landmark visible in both cameras."""
    v = b["center"] - a["center"]
    if a["camera"] is None:
        horizontal = math.hypot(float(v[0]), float(v[2]))
        if np.linalg.norm(v) <= 1e-9:
            return {"yaw": 0.0, "pitch": 0.0, "directional": False, "method": "none",
                    "note": "viewpoints share the same camera position"}
        return {"yaw": geometry.wrap(geometry.phi(v) - a["heading"]),
                "pitch": math.atan2(float(v[1]), horizontal), "directional": True, "method": "camera-pose"}
    bearing = geometry.wrap(geometry.phi(v) - a["heading"])
    if points is None or not len(points):
        return {"visible": False, "bearing": bearing, "method": "none",
                "note": "no shared 3D landmark is available for an image hotspot"}
    cam = a["camera"]
    direction = v / max(float(np.linalg.norm(v)), 1e-12)
    best = None
    for landmark in a["landmarks"] & b["landmarks"]:
        if landmark < 0 or landmark >= len(points):
            continue
        point = points[landmark]
        ray = point - a["center"]
        ray_norm = float(np.linalg.norm(ray))
        if ray_norm <= 1e-9:
            continue
        alignment = float(np.dot(ray / ray_norm, direction))
        if alignment <= 0:
            continue
        u, y, depth = geometry.project(point, a["center"], a["axes"], cam)
        u_b, y_b, depth_b = geometry.project(point, b["center"], b["axes"], b["camera"])
        if (depth <= 1e-6 or depth_b <= 1e-6 or not (0 <= u < cam["w"] and 0 <= y < cam["h"])
                or not (0 <= u_b < b["camera"]["w"] and 0 <= y_b < b["camera"]["h"])):
            continue
        if best is None or alignment > best[0]:
            best = (alignment, u, y, landmark)
    if best is None:
        return {"visible": False, "bearing": bearing, "method": "shared-landmark",
                "note": "no shared landmark projects inside both viewpoints"}
    _, u, y, landmark = best
    return {"visible": True, "x": round(float(u / cam["w"]), 5), "y": round(float(y / cam["h"]), 5),
            "bearing": bearing, "method": "shared-landmark", "landmark_index": int(landmark)}


def _gaps(frames):
    gaps, start = [], None
    for f in frames:
        if not f["registered"] and start is None:
            start = f["t"]
        if f["registered"] and start is not None:
            gaps.append([start, f["t"]])
            start = None
    if start is not None:
        gaps.append([start, frames[-1]["t"]])
    return gaps


def _load_landmarks(work, cands):
    """Per candidate: the set of landmarks it really observed. Returns (points array, source description)."""
    pts_file = work / "points_full.npz"
    points = np.load(pts_file)["positions"].astype(np.float64) if pts_file.is_file() else None
    obs_file = work / "observations.json"
    if obs_file.is_file():
        images = json.loads(obs_file.read_text()).get("images", {})
        for c in cands:
            if c["camera"] is not None:
                c["landmarks"] = set(images.get(c["fr"]["name"], []))
            else:
                # panorama node: union of the landmarks seen by its registered perspective faces
                stem = c["fr"]["stem"]
                c["landmarks"] = set().union(*[set(v) for k, v in images.items() if k.startswith(stem + "__")]) if images else set()
        return points, "tracked feature observations"
    if points is None or not len(points):
        for c in cands:
            c["landmarks"] = set()
        return None, "unavailable (no observations.json or sparse point cloud)"
    for c in cands:
        c["landmarks"] = viewgraph.landmarks_by_projection(c, points) if c["camera"] is not None else set()
    return points, "projection of the sparse point cloud (older reconstruction; occlusion is not considered)"


def _attach_panorama_viewpoints(work_rel, nodes, connections, extent):
    """Replace a perspective frame only when captured views prove near-complete spherical coverage."""
    result = panorama.build_all(work_rel)
    attached = {}
    candidates = result["panoramas"]
    for meta in candidates:
        coverage = meta.get("coverage") or {}
        if (
            meta.get("status") != "full_sphere"
            or not meta.get("is_complete_360")
            or coverage.get("sphere_area", 0.0) < panorama.FULL_SPHERE_MIN
            or meta.get("center_spread_ratio", 1.0) > 0.01
        ):
            continue
        center = np.asarray(meta["center"], dtype=np.float64)
        closest = min(nodes, key=lambda node: float(np.linalg.norm(np.asarray(node["position"]) - center)))
        if np.linalg.norm(np.asarray(closest["position"]) - center) > extent * 0.025:
            continue
        if closest["id"] in attached:
            continue
        attached[closest["id"]] = meta
        closest["frame"] = str(Path(work_rel) / "panoramas" / meta["file"]).replace("\\", "/")
        closest["panorama"] = True
        closest["heading_rad"] = round(float(geometry.phi(np.asarray(meta["basis_world"]["forward"]))), 5)

    node_by_id = {node["id"]: node for node in nodes}
    for connection in connections:
        meta = attached.get(connection["from"])
        if meta is None:
            continue
        target = node_by_id.get(connection["to"])
        marker = panorama.hotspot_for(meta, target["position"]) if target else None
        if marker is None:
            connection["hotspot"] = {"visible": False, "directional": False, "method": "reconstructed-panorama",
                                     "note": "destination direction is unavailable from this panorama"}
            continue
        connection["hotspot"].update({
            "yaw": marker["yaw"],
            "pitch": marker["pitch"],
            "directional": True,
            "method": "reconstructed-panorama",
        })

    statuses = [meta.get("status", "unknown") for meta in candidates]
    best_candidate = max(
        candidates,
        key=lambda meta: (meta.get("coverage") or {}).get("sphere_area", 0.0),
        default=None,
    )
    best_coverage = (best_candidate or {}).get("coverage") or {}
    best_sphere_area = best_coverage.get("sphere_area")
    best_horizon_band = best_coverage.get("horizon_band")
    if attached:
        note = (
            f"{len(attached)} viewpoint(s) have reconstructed equirectangular coverage of at least "
            f"{panorama.FULL_SPHERE_MIN:.1%} of the sphere, with low camera-center spread. "
            "Unseen pixels are not filled."
        )
    elif best_candidate:
        note = (
            "No candidate met the near-complete spherical-coverage and low-parallax requirements; "
            "no candidate is exposed as a 360° panorama. Best candidate coverage: "
            f"{best_sphere_area:.1%} of the sphere and {best_horizon_band:.1%} of the horizon band."
        )
    else:
        note = (
            "No complete 360° panorama was generated from this video. The viewer uses captured perspective frames; "
            "a 360° source or a full rotation captured from a stable camera position is required."
        )
    return {
        "status": "available" if attached else ("partial" if candidates else "unavailable"),
        "projection": "equirectangular",
        "horizontal_degrees": 360 if attached else 0,
        "vertical_degrees": 180 if attached else 0,
        "asset_method": "stitched_reconstructed_camera_views" if attached else None,
        "viewpoints": len(attached),
        "minimum_sphere_area_coverage": panorama.FULL_SPHERE_MIN,
        "best_candidate_sphere_area_coverage": best_sphere_area,
        "best_candidate_horizon_band_coverage": best_horizon_band,
        "partial_candidates": statuses.count("partial"),
        "horizontal_only_candidates": statuses.count("horizontal_360"),
        "note": note,
    }, result.get("skipped", [])


def _merge_video_fallback(nodes, connections, fallback_tour):
    """Keep every extracted frame while replacing registered frames with their pose-based viewpoints."""
    fallback_nodes = fallback_tour.get("nodes", [])
    if not fallback_nodes:
        return nodes, connections, None

    canonical = lambda value: str(value or "").replace("\\", "/")
    pose_by_frame = {
        canonical(node.get("source_frame", node.get("frame"))): node
        for node in nodes
    }
    pose_id_to_video_id = {}
    merged_nodes = []
    for fallback in fallback_nodes:
        source_frame = canonical(fallback.get("frame"))
        pose = pose_by_frame.get(source_frame)
        node = dict(fallback)
        node["source_frame"] = source_frame
        if pose is not None:
            node.update(pose)
            node["id"] = fallback["id"]
            node["seq"] = fallback["seq"]
            node["label"] = fallback.get("label") or pose.get("label", "")
            node["source_frame"] = source_frame
            node["has_pose"] = True
            pose_id_to_video_id[pose["id"]] = fallback["id"]
        else:
            node.update({"position": None, "heading_rad": 0.0, "camera": None, "has_pose": False})
        merged_nodes.append(node)

    if not pose_id_to_video_id:
        return nodes, connections, None

    pose_connections = []
    for connection in connections:
        if connection["from"] not in pose_id_to_video_id or connection["to"] not in pose_id_to_video_id:
            continue
        merged = dict(connection)
        merged["from"] = pose_id_to_video_id[connection["from"]]
        merged["to"] = pose_id_to_video_id[connection["to"]]
        pose_connections.append(merged)

    merged_connections = list(pose_connections)
    pose_ids = set(pose_id_to_video_id.values())
    video_by_id = {node["id"]: node for node in merged_nodes}
    pairs = {(connection["from"], connection["to"]) for connection in merged_connections}
    fallback_connections = []
    for connection in fallback_tour.get("connections", []):
        source, target = connection.get("from"), connection.get("to")
        if source not in video_by_id or target not in video_by_id or (source in pose_ids and target in pose_ids):
            continue
        if connection.get("hotspot", {}).get("verified") is not True or (source, target) in pairs:
            continue
        merged_connections.append(dict(connection))
        fallback_connections.append(connection)
        pairs.add((source, target))

    ids = {node["id"] for node in merged_nodes}
    adjacency = {node_id: set() for node_id in ids}
    valid_links = True
    for connection in merged_connections:
        source, target = connection["from"], connection["to"]
        valid_links &= source in ids and target in ids and source != target
        if source in ids and target in ids:
            adjacency[source].add(target)
            adjacency[target].add(source)
    unseen, components = set(ids), []
    while unseen:
        pending = [unseen.pop()]
        component = []
        while pending:
            current = pending.pop()
            component.append(current)
            neighbours = adjacency[current] & unseen
            unseen.difference_update(neighbours)
            pending.extend(neighbours)
        components.append(sorted(component, key=lambda node_id: video_by_id[node_id]["seq"]))
    components.sort(key=lambda component: (-len(component), video_by_id[component[0]]["seq"]))
    metadata = {
        "video_viewpoints": len(merged_nodes),
        "pose_viewpoints": len(pose_ids),
        "fallback_viewpoints": len(merged_nodes) - len(pose_ids),
        "fallback_connections": len(fallback_connections),
        "components": components,
        "passed": valid_links and len(merged_nodes) == len(fallback_nodes),
    }
    if not metadata["passed"]:
        raise PipelineError("The merged pose/video navigation graph failed validation.", 500)
    return merged_nodes, merged_connections, metadata


def build(work_rel: str, is_360: bool, fallback_tour=None):
    work = config.resolve(work_rel)
    recon = json.loads((work / "reconstruction.json").read_text())
    cands = _frame_candidates(recon, work_rel)
    _choose_nodes(cands)                      # refuses early when the camera never moved
    points, evidence = _load_landmarks(work, cands)

    graph, kept, d_min = None, None, None
    for density in (1.0, 2.0, 4.0):          # a too-sparse selection can drop the overlap between neighbours: try denser before giving up
        kept, d_min = _choose_nodes(cands, density)
        graph = viewgraph.build([{"center": c["center"], "axes": c["axes"], "camera": c["camera"], "landmarks": c["landmarks"],
                                  "t": c["fr"]["t"]} for c in kept], points)
        if len(graph["main"]) >= 0.9 * len(kept):
            break
    if len(kept) < 2:
        raise PipelineError(
            "Not enough distinct camera positions for a tour.", 422)
    main = graph["main"]
    order = {old: old for old in range(len(kept))}
    kept_ids = {id(c) for c in kept}
    dropped = [c for c in cands if id(c) not in kept_ids]

    nodes = []
    for old in range(len(kept)):
        c = kept[old]
        fr = c["fr"]
        i = order[old]
        nodes.append({
            "id": f"n{i}", "seq": i, "label": f"Viewpoint {i + 1}", "frame": fr["file"], "panorama": bool(is_360),
            "source_frame": fr["file"],
            "position": [round(float(x), 5) for x in c["center"]], "heading_rad": round(float(c["heading"]), 5),
            "camera": None if c["camera"] is None else {k: c["camera"][k] for k in ("w", "h", "fx", "fy", "cx", "cy")},
            "time_sec": fr["t"], "landmarks": len(c["landmarks"]),
        })

    connections, kinds = [], {"covisibility": 0, "loop_closure": 0}
    for m in graph["edges"]:
        if m["i"] not in order or m["j"] not in order:
            continue
        i, j = order[m["i"]], order[m["j"]]
        a, b = kept[m["i"]], kept[m["j"]]
        d = float(np.linalg.norm(a["center"] - b["center"]))
        kinds[m["kind"]] += 1
        proof = {"kind": m["kind"], "verified": True, "inliers": m["shared"], "shared_landmarks": m["shared"], "overlap": round(m["overlap"], 3),
                 "parallax_deg": None if m["parallax_deg"] is None else round(m["parallax_deg"], 2), "confidence": m["confidence"], "evidence": "shared 3D landmarks"}
        for src, dst, sa, sb in ((i, j, a, b), (j, i, b, a)):
            hs = hotspot(sa, sb, points)
            hs.update(proof)              # the database keeps the hotspot JSON, so the proof travels with the link
            connections.append({"from": f"n{src}", "to": f"n{dst}", "hotspot": hs, "distance": round(d, 5), "kind": m["kind"],
                                "verified": True, "inliers": m["shared"], "confidence": m["confidence"]})

    panorama_coverage = None
    panorama_skipped = []
    if not is_360:
        centers = np.array([c["center"] for c in cands])
        extent = float(np.linalg.norm(centers.max(axis=0) - centers.min(axis=0))) or 1.0
        panorama_coverage, panorama_skipped = _attach_panorama_viewpoints(
            work_rel, nodes, connections, extent)

    prev = json.loads((work / "points_preview.json").read_text())
    pts = np.array(prev["positions"]).reshape(-1, 3)
    floor_pts = []
    if len(pts):
        lo, hi = np.percentile(pts[:, 1], [5, 95])
        band = pts[(pts[:, 1] >= lo) & (pts[:, 1] <= hi)]
        band = band[np.random.default_rng(1).permutation(len(band))[:8000]]
        floor_pts = np.round(band[:, [0, 2]], 4).tolist()
    allxz = np.array([[n["position"][0], n["position"][2]] for n in nodes] + floor_pts)
    bounds = {"minx": float(allxz[:, 0].min()), "maxx": float(allxz[:, 0].max()),
              "minz": float(allxz[:, 1].min()), "maxz": float(allxz[:, 1].max())}

    frames = recon.get("frames", [])
    registered_images = max(0, int(recon.get("registered_images", sum(bool(f.get("registered")) for f in frames))))
    total_images = max(registered_images, max(0, int(recon.get("total_images", len(frames)))))
    reg_frac = registered_images / total_images if total_images else 0.0
    warnings = []
    if reg_frac < 0.6:
        warnings.append(f"Only {reg_frac:.0%} of images were registered; parts of the property are not covered.")
    gaps = _gaps(frames)
    if gaps:
        warnings.append("Some parts of the video were not tracked; see coverage gaps.")
    sub = (recon.get("sfm") or {}).get("registered_per_model") or []
    if len(sub) > 1:
        warnings.append(f"The reconstruction split into {len(sub)} separate models ({', '.join(map(str, sub))} images); only the largest is navigable. "
                        "Film one continuous path with overlap between rooms (pause on the doorway) to join them.")
    if dropped:
        t = sorted(c["fr"]["t"] for c in dropped)
        warnings.append(f"{len(dropped)} registered frame(s) between {t[0]:.1f}s and {t[-1]:.1f}s were combined by the viewpoint-spacing limit; "
                        "their images remain available in the source video.")
    if not graph["edges"]:
        warnings.append("No viewpoint pairs had enough verified shared landmarks; every selected viewpoint is retained and selectable without a fabricated link.")
    if evidence.startswith("unavailable"):
        warnings.append("Feature observations and a sparse point cloud are unavailable, so no 3D viewpoint links could be verified.")
    if len(graph["components"]) > 1:
        warnings.append(f"{len(graph['components'])} verified graph components were found; all components are retained without invented cross-links.")
    if is_360:
        warnings.append("Camera positions come from the four horizontal views of each panorama; floor and ceiling are not used for tracking.")
    warnings.append("Positions are in arbitrary model units until a real distance is entered.")

    ids = {n["id"] for n in nodes}
    adj = {}
    for c in connections:
        adj.setdefault(c["from"], set()).add(c["to"])
    components = [[f"n{i}" for i in component] for component in graph["components"]]
    component_ok = True
    for component in components:
        reached, todo = set(), [component[0]] if component else []
        while todo:
            x = todo.pop()
            if x in reached:
                continue
            reached.add(x)
            todo += list(adj.get(x, ()))
        component_ok &= reached == set(component)
    checks = [
        {"check": "every link is backed by shared landmarks", "ok": all(c["verified"] and c["inliers"] >= graph["min_shared"] for c in connections), "detail": ""},
        {"check": "links reference existing viewpoints", "ok": all(c["from"] in ids and c["to"] in ids and c["from"] != c["to"] for c in connections), "detail": ""},
        {"check": "all viewpoints are retained in a verified graph component", "ok": sum(map(len, components)) == len(ids), "detail": f"{len(components)} component(s)"},
        {"check": "each reported component is internally navigable", "ok": component_ok, "detail": ""},
    ]
    validation = {"passed": all(c["ok"] for c in checks), "checks": checks}
    if not validation["passed"]:
        raise PipelineError("Viewpoint graph validation failed, nothing was published: "
                            + "; ".join(c["check"] for c in checks if not c["ok"]), 500)

    merged_tour = _merge_video_fallback(nodes, connections, fallback_tour) if fallback_tour else None
    if merged_tour:
        nodes, connections, merge_summary = merged_tour
        manifest_graph = {
            "method": "pose-verified graph with verified visual-overlap fallback links",
            "evidence": evidence,
            "min_shared_landmarks": graph["min_shared"],
            "viewpoints_considered": len(cands),
            "viewpoints_in_walkthrough": merge_summary["video_viewpoints"],
            "viewpoints_left_out": 0,
            "components_found": len(merge_summary["components"]),
            "links": len(connections),
            "components": merge_summary["components"],
            "main_component": merge_summary["components"][0] if merge_summary["components"] else [],
            "unconnected_viewpoints": [node_id for component in merge_summary["components"][1:] for node_id in component],
            "neighbour_links": kinds["covisibility"],
            "loop_closures": kinds["loop_closure"],
            **merge_summary,
        }
    else:
        manifest_graph = {"method": "shared 3D landmarks (feature correspondences triangulated by structure from motion)", "evidence": evidence,
                          "min_shared_landmarks": graph["min_shared"], "viewpoints_considered": len(kept), "viewpoints_in_walkthrough": len(nodes),
                          "viewpoints_left_out": len(dropped), "components_found": len(graph["components"]), "links": len(graph["edges"]),
                          "components": components, "main_component": [f"n{i}" for i in main],
                          "unconnected_viewpoints": [f"n{i}" for i in range(len(nodes)) if i not in set(main)],
                          "neighbour_links": kinds["covisibility"], "loop_closures": kinds["loop_closure"]}

    manifest = {
        "is_360": is_360, "units": "model_units", "extents": recon["extents"],
        "mode": "pose_and_video_fallback" if merged_tour else "pose",
        "coverage": {"registered_fraction": round(reg_frac, 3), "registered_images": registered_images,
                     "total_images": total_images, "untracked_time_ranges_sec": gaps},
        "graph": manifest_graph,
        "validation": validation,
        "floorplan": {"kind": "point_density", "points": floor_pts, "bounds": bounds,
                      "note": "Top-down projection of reconstructed points; walls and rooms are not extracted."},
        "panorama_coverage": panorama_coverage or {
            "status": "source_declared_not_content_verified",
            "projection": "equirectangular",
            "horizontal_degrees": 360,
            "vertical_degrees": 180,
            "asset_method": "original_extracted_video_frame",
            "note": "The source was declared as 360° and checked for 2:1 frame dimensions; image content was not independently verified.",
        },
        "panorama_generation": {"skipped": panorama_skipped},
        "points_path": str(Path(work_rel) / "points_preview.json").replace("\\", "/"),
        "warnings": warnings,
    }
    if merged_tour:
        manifest["coverage"]["viewpoints"] = merge_summary["video_viewpoints"]
        manifest["validation"]["checks"].append({
            "check": "all extracted video viewpoints are retained with available poses",
            "ok": merge_summary["passed"],
            "detail": f"{merge_summary['pose_viewpoints']} pose-based, {merge_summary['fallback_viewpoints']} frame-only",
        })
        manifest["validation"]["passed"] &= merge_summary["passed"]
        if merge_summary["fallback_viewpoints"]:
            warnings.append(
                f"{merge_summary['fallback_viewpoints']} extracted viewpoint(s) have no reconstructed camera pose; "
                "they remain available as frame-only views where visual-overlap links exist."
            )
    (work / "tour_manifest.json").write_text(json.dumps(manifest))
    return {"nodes": nodes, "connections": connections, "validation": manifest["validation"],
            "manifest_path": f"{work_rel}/tour_manifest.json", "points_path": manifest["points_path"]}
