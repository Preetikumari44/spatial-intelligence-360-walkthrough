# Panoramas, hotspots and sensors (2026-11-08, second pass)

Scope of this pass, stated plainly. Built and tested here: pose-based panorama stitching with honest coverage labels, panorama hotspot maths, a sensor-metadata report.
NOT built: the new frontend viewer, new Java job states, real-video tests (see section 4).

## 1. New code
| File | What it does |
|---|---|
| `ai-service/app/panorama.py` | Groups registered frames that were filmed from (nearly) the same position, warps each onto an equirectangular 2:1 canvas using its SfM rotation and intrinsics, matches exposure, feather-blends, measures seam error. `build_all(work)` does this for a whole reconstruction. `hotspot_for(meta, target)` gives yaw, pitch and the 0..1 pixel position of another viewpoint, from relative camera positions in the panorama's own axes |
| `ai-service/app/sensors.py` | Reports what the video really contains (GPS container tag, motion-data tracks) via ffprobe. Does not decode or fuse IMU/compass data |
| `ai-service/app/main.py` | `POST /video/panoramas` (body like `/video/tour`) and `POST /video/sensors` (body like `/video/probe`). New routes only, nothing changed |
| `ai-service/tests/test_panorama.py` | 8 tests |

## 2. What a panorama claims
`status` is `full_sphere` (>= 99.5 % of the sphere), `horizontal_360` (whole +-20 deg horizon band, floor/ceiling empty) or `partial` (**not** a 360 panorama). Only `full_sphere` assets are attached to a tour node and presented as spherical look-around; horizon-only assets remain unexposed as 360° views. Unseen pixels are never filled.
Unseen pixels stay empty and a mask is saved: no inpainting, no stretching of a flat frame, `generated_regions: none`. Each panorama has sphere/horizon coverage, seam error (grey levels),
camera-centre spread, confidence and the source frames. A single frame or a narrow sweep is labelled `partial`.

## 3. Tests actually run (Linux sandbox, CPU)
* AI-service suite: **110 passed, 2 skipped, 2 failed** (the same 2 Open3D tests; Open3D is not installed in the sandbox).
* Panorama: 12 views with known poses cut from a ground-truth equirectangular image -> `horizontal_360`, horizon coverage 100 %, sphere coverage about 70 %, seam error 0.6 grey levels, pixels match the ground truth (after a small blur that absorbs a sub-pixel offset of the reference renderer). Narrow sweep, single frame and exposure-mismatched views behave as described above.
* `build_all` on a reconstruction of the synthetic room (camera turning on the spot): 1 panorama, `partial` (the room has no filmed back wall); a sparse walk elsewhere is skipped with a reason.
* Sensors: a plain MP4 reports no GPS / motion tracks; an MP4 with a location tag is read correctly.

## 4. NOT done (do not assume these work)
* **Real videos**: tests A-F of the master prompt were not run. No real apartment/house/office video, no real revisit video (loop closure is unit-tested only), no real insufficient-overlap video.
* **COLMAP** was not run (Windows build, Linux sandbox). Java backend, PostgreSQL, PowerShell scripts, frontend build and browsers were not run.
* **Frontend**: no new panorama viewer, hotspot overlay, room panel, floor panel or mobile touch handling was written. The existing Marzipano walkthrough is unchanged and does not yet read `/video/panoramas` output.
* **Not wired into the job flow**: the endpoints exist but `ProcessingService` does not call them; the new states (OPTIMIZING_CAMERA_GRAPH, GENERATING_PANORAMAS, GENERATING_HOTSPOTS, VALIDATING_WALKTHROUGH...) were not added to the Java enum or the database.
* **Panorama limits**: needs several frames filmed from one spot. A normal walk-through rarely has that, so most real videos will give few or no panoramas; the walkthrough then stays a 2D/3D viewpoint tour. No depth-assisted reprojection, novel-view synthesis, Gaussian-splatting views or inpainting; stitching ignores parallax (the centre spread is reported and lowers confidence).
* **Sensors**: GPS tag and motion tracks are only detected. No gyroscope/accelerometer/compass decoding, no visual-inertial fusion, no heading alignment.
* **Matching**: still ORB (no-COLMAP tour) and COLMAP SIFT; SuperPoint/LightGlue not added. No multi-floor support, no automatic room classification, no duplicate-viewpoint merge beyond the verified-link rule.
