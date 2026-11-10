# Viewpoint connection fix (2026-11-08)

Blunt record of what was wrong, what changed, what was run, and what was NOT done.

## 1. Root cause
The viewpoints were real, but the **links between them were not evidence-based**:

1. **Pose-based tour (`tour.py`, COLMAP / OpenCV SfM)**: every viewpoint was linked to its 4 nearest neighbours *by camera distance* and unconditionally to the next
   registered frame (`pairs.add((i, i + 1))`). Nothing checked that two linked viewpoints looked at the same physical features. Two cameras close together on
   opposite sides of a wall, or two consecutive frames after a jump, were linked anyway. The SfM stage also threw away *which* 3D landmark each frame observed,
   so the information needed to verify a link was never saved.
2. **No-COLMAP tour (`viewpoints.py`)**: every selected viewpoint was linked to the next one in video order, even when the pair failed verification
   (it was only flagged `verified:false` and still navigable). Viewpoints were spaced by colour-histogram change, not by guaranteed overlap, and hotspot direction
   came from a 2D affine heuristic, not from the camera pose.
3. **COLMAP sub-models**: when COLMAP split the video into several unrelated models, only the largest was kept and the rest disappeared silently.

## 2. What changed
**New**: `ai-service/app/viewgraph.py`, `ai-service/tests/test_viewgraph.py`, this file, `docs/viewpoint_connection_run_2026-11-08.json` (the real run record).

**Modified**
| File | Change |
|---|---|
| `ai-service/app/geometry.py` | `parse_points_ex` (keeps COLMAP point ids), `parse_image_observations` (which landmark each image saw) |
| `ai-service/app/sfm.py` | OpenCV SfM returns per-image landmark observations |
| `ai-service/app/reconstruct.py` | persists `observations.json` next to `points_full.npz`; reports every COLMAP sub-model instead of silently dropping them |
| `ai-service/app/tour.py` | links come from `viewgraph.build` (shared landmarks), no distance / `i+1` links; denser re-selection if the first choice is too sparse to link; only the main connected component is published; the rest is reported; graph validation; proof (`shared_landmarks`, `overlap`, `parallax_deg`, `confidence`) stored in the hotspot JSON |
| `ai-service/app/viewpoints.py` | viewpoints chosen so neighbours **overlap**; links verified by essential-matrix (cheirality-checked) or homography RANSAC on ratio-tested ORB matches; hotspot direction from the recovered relative pose; a break in overlap makes no link; unconnected stretches are left out and reported |
| `ai-service/app/config.py`, `.env.example` | `TOUR_MIN_SHARED_LANDMARKS`, `TOUR_MIN_OVERLAP`, `TOUR_MIN_PARALLAX_DEG`, `TOUR_MAX_VIEW_ANGLE_DEG`, `TOUR_LOOP_MIN_GAP_SEC`, `TOUR_TARGET_VIEWPOINTS`, `TOUR_ALLOW_UNVERIFIED_LINKS` |
| `ai-service/tests/test_tour.py`, `test_viewpoints.py` | one fixture now supplies landmark observations; the old "scene cut keeps an unverified link" test was replaced by tests of the new contract (no link across a cut; the old behaviour only behind `TOUR_ALLOW_UNVERIFIED_LINKS=1`) |
| `docs/ARCHITECTURE_TWO_MODES.md` | link and hotspot rows updated |

Not touched: Java backend, database migrations, frontend, scripts, authentication, COLMAP bundle, YOLO/depth/measurement code. **No API route was added or removed.**
Responses gained fields only (`validation`, link `confidence`, hotspot `shared_landmarks` / `overlap` / `parallax_deg` / `evidence`); the old keys are unchanged. No new dependency.

## 3. Algorithm
Pose-based tour (COLMAP or OpenCV SfM):
1. Registered frames become candidates, thinned by camera distance (denser retries if the result cannot be linked).
2. Landmark sets come from `observations.json` (the real tracks). Older reconstructions without it fall back to projecting the sparse cloud (weaker, labelled).
3. A pair is linked only if it shares >= `TOUR_MIN_SHARED_LANDMARKS` landmarks (adaptive for sparse models, floor 8), overlap >= 0.12, shared points project in front of and
   inside both cameras (>= 50 %), median parallax >= 0.3 deg and viewing directions differ by <= 100 deg.
4. Each viewpoint keeps its best 4 links; a strongest-link spanning forest guarantees everything that *can* be connected is. Links between moments >= 8 s apart are
   labelled `loop_closure` and need 1.5x the shared landmarks, unless they are the only bridge.
5. Components that do not join the main walkthrough are reported (time range, warning) and left out. The graph is validated (links verified, reachable) before publishing.

No-COLMAP tour: greedy overlap-driven selection, essential-matrix / homography verification, pose-derived hotspots, same component rule.

## 4. What was actually run (Linux sandbox, CPU only, synthetic videos)
* AI-service test suite: **102 passed, 2 skipped, 2 failed**. The 2 failures are `open3d` capability tests; Open3D is not installed in the sandbox (they were failing before my changes for the same reason). Dense mesh and Gaussian tests were not run here.
* New: 9 graph tests (links proven by shared landmarks; no link across a cut; no link through a wall; loop closure labelled and stricter; parallax required; landmarks behind the camera ignored; disconnected stretch left out; refusal when nothing links), 2 reworked Pipeline-A tests.
* End-to-end through the FastAPI app (`/video/probe` -> `/video/frames` -> `/video/viewpoints` -> `/video/reconstruct` -> `/video/tour`), OpenCV SfM backend, on generated videos
  (record: `docs/viewpoint_connection_run_2026-11-08.json`): 90-, 120- and 240-frame room walks all produced one connected, fully verified graph (8, 11 and 13 pose-based
  viewpoints; every link shared >= 278 landmarks); the static video was rejected; the flat pan was processed (it is a flat texture, so the 3D result is degenerate); a second independent video worked.

## 5. NOT done / NOT verified (read this)
* **COLMAP was not run.** The bundled COLMAP is a Windows build; this sandbox is Linux. The COLMAP-side changes (observations from `images.txt`, sub-model report) are covered by parser logic and tests of the shared code path, not by a COLMAP run. Run `scripts\test-full-pipeline.ps1 -Full` on your machine.
* **Java backend, PostgreSQL, PowerShell scripts, the frontend build and the browser UI were not run** (no Maven / database in the sandbox). The Java side stores the connection's `hotspot` JSON as before.
* No real phone video was used; all videos are generated. Loop closure is covered by unit tests only, not by a real revisit video.
* SIFT/SuperPoint/LightGlue were **not** added: Pipeline A uses ORB, COLMAP uses its own SIFT. Sensor (compass/IMU/GPS) data is not read.
* No stitched 360 panoramas: 360 footage still uses the extracted 2:1 source frames, labelled `source_declared_not_content_verified`. No automatic room classification (rooms stay manual). No per-stage retry for sub-steps beyond what already existed.
* Because unverifiable links are no longer invented, a video with a hard cut or a very fast turn now yields a **shorter** walkthrough (the main connected stretch) plus a warning, instead of a tour with a jump. Set `TOUR_ALLOW_UNVERIFIED_LINKS=1` to restore the old behaviour.
* Re-running a reconstruction is needed for old projects to get `observations.json`; older ones fall back to the weaker point-projection check.

## 6. Follow-up implementation status

The initial report above predates these changes; the following is the current behavior:

* Pipeline A checks temporal neighbors and appearance-retrieved frame pairs, but only creates links after geometric verification. It retains all selected viewpoints, including disconnected components, instead of dropping a disconnected stretch.
* Pose-based image hotspots require a shared reconstructed landmark that projects inside both camera images. Flat video without 3D poses has no known image hotspot; its verified links remain available in the connected-view list. These markers represent shared visual landmarks, not detected doorways.
* The walkthrough UI supports manual room creation/editing, room-type selection, viewpoint assignment/renaming, search, and disconnected-component navigation. The spatial map draws only explicitly verified links.
* Existing real-frame validation: the active “Views” project's 92 frames produced 92 viewpoints and 444 directed, geometrically verified links in one component; 599 candidate pairs were evaluated. A later mixed-tour validation on this project retained all 92 frames, added 11 pose-backed positions, and produced 490 verified directed links in one component.
* Existing reconstruction validation: a temporary copy of the pose-based inputs produced 11 viewpoints and 58 verified directed links in one component, with 29 shared-landmark image hotspots. The reconstruction reports only its largest of three SfM models as navigable; preserving other SfM models is not implemented.
* Validation runs used temporary output and left the project files/database unchanged. Existing tours are not migrated automatically; rerunning processing upgrades the frame tour with matched pose data and preserves unmatched frames as honest frame-only viewpoints. Room labels and assignments remain user-authored; automatic room classification and doorway detection are not implemented.

## 7. Interactive navigation and panorama integration

The pose-based tour now invokes the existing SfM panorama stitcher. A generated image replaces a perspective viewpoint only when measured spherical coverage is at least 99.5% and camera-center spread is at most 1% of the scene extent. Horizon-only coverage is not exposed as 360° look-around. Navigation yaw/pitch is calculated from the panorama's reconstructed world basis. Partial sweeps remain ordinary perspective frames; the stitcher does not fill unseen pixels.

The viewer now keeps one Marzipano instance while switching between validated equirectangular viewpoints, uses scene transitions, validates that panorama images are 2:1, and exposes verified connected destinations as click targets. Sequential Next/Previous controls were removed; a back-history control remains. Perspective frames are explicitly labelled as non-360, with connected-view actions rather than invented doorway/floor hotspots. Selecting a room or viewpoint in the Spatial Map opens that view in the walkthrough.

The pose tour is merged into the complete extracted-frame tour by source-frame identity. Matching frames receive reconstructed positions; unmatched frames keep `position: null` and are excluded from the spatial map rather than being plotted at the origin. Verified fallback links are retained only when at least one endpoint lacks a pose. Room names and assignments survive tour replacement by matching source frame or capture time.

End-to-end reprocessing of the actual uploaded “Views” video completed on 2026-11-10 (job `3567162c-0d4f-4934-b6c3-eeaa85529c8b`). The pipeline extracted 92 viewpoints and 444 verified frame-tour links, then COLMAP registered 18/36 sampled images with 441 sparse points. Dense reconstruction wrote a 53,012-triangle mesh and training wrote 2,000 Gaussians. The saved project API now returns 92 nodes, 478 verified connections, 8 pose-backed nodes and 84 frame-only nodes. All links reference saved nodes; the saved graph manifest passed validation with one navigable component. Refreshing `/walkthrough` reopened “Views” with 92 viewpoints; clicking the verified connection to Viewpoint 02 changed the active position to `2/92`. No room assignments existed before reprocessing, and none were created automatically.

The job log’s “Walkthrough upgraded with 92 pose-based viewpoints” line overstated the pose count because the logger counted all returned tour nodes. The saved manifest and project API are authoritative (8 pose-backed, 84 frame-only); the logger is corrected in code. The earlier temporary-copy validation also passed with 11 pose-backed and 81 frame-only views; it did not alter the project.

Real-data panorama limitation: the active reconstruction produced one panorama candidate with only 17.59% horizon-band coverage; it is correctly rejected as partial. No node is presented as 360° and no complete panoramas were generated from this upload. A real 360° equirectangular source or a sufficiently complete rotation captured from a stable camera position is required for the true 360° acceptance criteria. Room-to-room links are verified visual connections, not detected doorways; room names and assignments remain manual, and wall/door detection and automatic room classification are not implemented.

## 8. Fresh rerun after strict spherical-coverage gate

The existing “Views” video (`ed71300a-5154-461e-a945-ee0044ddf6de`, 45.92 seconds) was processed twice on 2026-11-10. The first job, `fb0bda5e-3a66-465c-ae12-ab44c9b8ac5f`, extracted all 92 viewpoints and 444 verified links, but advanced reconstruction stopped before COLMAP because only 809 MB of RAM was free and the configured minimum is 1200 MB. That attempt temporarily replaced the prior pose tour with a frame-only tour.

The backend was changed to keep any existing pose-backed tour until a replacement has passed validation; `mvn -q -DskipTests compile` passed. After freeing memory, a fresh job `86fef401-4ac8-4f48-87c7-4cfd83a5a729` completed. It used the minimal COLMAP plan at 2708 MB free RAM and registered 18/36 sampled images, with 441 sparse points. COLMAP produced three disconnected models `[18, 15, 10]`; only the largest is in the spatial graph. The later stages produced a 53,012-triangle mesh and 2,000 Gaussians.

The saved project API was checked after completion: 92 viewpoints, 478 verified connections, 8 pose-backed nodes, 84 frame-only nodes, zero invalid links, one validated navigation component, zero panoramas and zero room assignments. The tour manifest passed graph validation. The first and last labels/times are `Viewpoint 01` at 1.463 seconds and `Viewpoint 92` at 45.252 seconds. Comparing the previous and fresh extracted-frame manifests found all 92 labels/timestamps matched; no manual room assignments existed to preserve. After refreshing the browser, all 92 views loaded; clicking a verified connection moved to Viewpoint 02, and refreshing again retained that selection.

The best panorama candidate covered only 8.76% of the sphere and 17.39% of the horizon band; it was rejected. No view is presented as 360°. Controls for drag/touch/wheel spherical look-around are explicitly configured in Marzipano, but cannot be validated on this uploaded source because no eligible spherical image exists. The frame-only views are not 360° and do not support full camera rotation. Room labels are manual; automatic room classification and doorway detection are unavailable. The uploaded recording therefore passes video extraction, tour persistence, pose reconstruction, verified click navigation, and refresh persistence, but does not meet the true-360° or room-entry acceptance criteria.

## 9. Backend diagnostics and blank-frame follow-up

The VS Code diagnostics for `ProcessingService.java` were not independent missing setters/imports: Lombok's processor failed in the Java language server with `NoSuchFieldException: com.sun.tools.javac.code.TypeTag :: UNKNOWN`, followed by false “cannot find symbol” errors for Lombok-generated accessors. The backend POM inherited Lombok 1.18.34, which predates JDK 25 support. Lombok is now pinned through the Maven-managed `lombok.version` property to 1.18.48. Maven resolved that version, the backend compiled and restarted, and the Problems tool reports no diagnostics for `ProcessingService.java`.

The saved frame paths are valid. All 92 project-file GET requests returned HTTP 200, `image/jpeg`, and nonempty bodies. The browser loaded Viewpoints 01, 02 and 03 from their corresponding `f_000044.jpg`, `f_000088.jpg` and `f_000096.jpg` assets at 360×640; normal viewpoint changes produced no console or network errors. The black areas beside the portrait frame are aspect-ratio letterboxing, not a missing image. The blob loader now keys results to the requested path so a prior frame cannot flash as the new selection loads; it displays loading and explicit error/retry states. A simulated HTTP 503 showed the error and retry action, and retry restored the actual image. A backend API test now checks that project frame files are served as JPEG.

Tour persistence also fails closed for pose data: a camera position is accepted only when all three coordinates are finite numbers and any explicit `has_pose` flag is true. Pose-less nodes are persisted with zero coordinates/heading and no camera object; the frontend only plots nodes explicitly marked `hasPose: true`.
