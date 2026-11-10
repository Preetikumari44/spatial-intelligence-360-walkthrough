# Architecture: two independent pipelines

```
upload video -> POST /video/frames -> Pipeline A: POST /video/viewpoints  -> tour published (TOUR_READY)   <- walkthrough opens here
                                   \-> Pipeline B (optional): /video/reconstruct -> /video/tour (poses) -> /video/model -> /video/splat
```
Pipeline A (`ai-service/app/viewpoints.py`) imports no COLMAP, Open3D or PyTorch (a test proves it). It reads `frames.json` and writes `tour_manifest.json`.
Pipeline B is the existing COLMAP / OpenCV-SfM / Open3D / Gaussian path. In `ProcessingService.runVideo` it runs inside a try block after the tour is saved:
any failure becomes the job message "Completed with limitations: ..." and the tour stays. A successful pose reconstruction upgrades the tour only when it
includes every extracted frame; if registration or graph filtering omits frames, the complete frame-based tour stays available. Cancelling the job still cancels it.

## What Pipeline A does and does not claim
| Item | Behaviour |
|---|---|
| Viewpoints | every real extracted frame, with original timestamps and frame indices; consecutive viewpoints link only when visual overlap is verified; disconnected groups remain selectable rather than being dropped |
| Labels | neutral: "Viewpoint 01", "Area 1". **Room types (kitchen, bedroom...) are not guessed**: no classifier is bundled |
| Areas | a new area starts at a detected cut, or at a strong appearance change with too little verified overlap |
| Links | **verified only** (see VIEWPOINT_CONNECTION_FIX.md). `sequence` = consecutive viewpoints that pass essential-matrix / homography RANSAC on ratio-tested ORB matches; `revisit` = far-apart moments (>= 8 s) verified the same way with >= 45 inliers, at most 2 per viewpoint. A cut or break in overlap makes **no** link; all resulting groups remain available in the viewpoint list. `TOUR_ALLOW_UNVERIFIED_LINKS=1` restores video-order links across breaks (flagged `verified:false`) |
| Hotspots | direction from the recovered relative camera pose (essential matrix; focal length estimated unless a calibration file is configured); image flow only as fallback; `approximate:true`. Links pointing behind the camera or with no estimable direction are listed under "Not visible from here" |
| 360 footage | nodes are panoramas, links listed (`directional:false`): direction needs camera poses, so no yaw is invented |
| Flat video | 2D viewpoint navigation only. Never stretched into a panorama |
| Validation | images and thumbnails exist, every extracted frame appears exactly once as a viewpoint, links reference real nodes, hotspots inside the image, timestamps ordered. On failure nothing is published |
| 3D | none: `has_pose=false`, no floor plan, no measurements until Pipeline B succeeds |

## Data
`V4__tour_without_poses.sql` adds `navigation_nodes.has_pose BOOLEAN NOT NULL DEFAULT TRUE` (additive; existing rows stay TRUE). Link metadata (`kind`, `verified`, `inliers`, `method`) lives in the hotspot JSON.
The viewpoint tour is written to `jobs/<id>/tour/`, separate from `jobs/<id>/work/` which Pipeline B owns, so a failed or restarted reconstruction cannot delete it.
