# COLMAP integration and test report (2026-11-05)

Read this first. PASS means the check ran in the environment named. Nothing here ran on Windows.

## 1. What was found in the supplied COLMAP package
- `colmap.exe` reports the **1.0 line** (CPU build). Its option names were read from the binary itself: extraction/matching options are
  `FeatureExtraction.*` / `FeatureMatching.*` (`use_gpu`, `max_image_size`, `num_threads`); `SiftExtraction.max_image_size` **does not exist** in
  it, which is exactly your error. `SiftExtraction.max_num_features`, `SequentialMatching.overlap/loop_detection/vocab_tree_path`, `Mapper.*` do exist.
- The binary says "Dense stereo reconstruction requires CUDA" and "Skipping patch match stereo because CUDA is not available". So
  `patch_match_stereo` / `stereo_fusion` **cannot run** with this build; dense geometry comes from the Open3D depth-fusion path, and the report says so.
- The package has 107 DLLs but **not** the Visual C++ runtime. Reading the import tables of every file showed the only non-Windows DLLs missing are
  `vcruntime140`, `vcruntime140_1`, `msvcp140`, `msvcp140_1`, `msvcp140_2`, `vcomp140`. If they are absent on your PC, `colmap.exe` fails with 0xC0000135.
- 107 `*_test.exe` unit-test programs in the package were **not** copied (not used at run time; ~40 MB saved). All DLLs, `colmap.exe`, `plugins/` and `COLMAP.bat` are in `tools/colmap/`.

## 2. Changes
New: `colmap_locator.py` (override > bundled > PATH; bin folder prepended to PATH for every child process; loader-error explanations; VC runtime check),
`colmap_validate.py` (database checks after extraction and matching), `/colmap/status` endpoint, `scripts/install-colmap.ps1`, `check-colmap.ps1`,
`setup-all.ps1`, `test-full-pipeline.ps1`, tests `test_colmap_bundle.py`, `test_frames_adaptive.py`, `test_tour.py`.
Changed: `colmap_compat.py` (CUDA detection, undistorter / patch-match / fusion / bundle-adjuster builders, CUDA-gated; loop closure only with a vocab file),
`reconstruct.py` (complete stdout/stderr per COLMAP step in `colmap_logs/`, DB validation, loader errors), `video_pipeline.py` (motion-adaptive sampling),
`make_test_video.py` (a real 3D parallax room; the old flat pan cannot be reconstructed by any SfM), `.env.example`, `_common.ps1`, `start-ai.ps1`, README.

Adaptive sampling: measures motion every ~8 probes/s, keeps the sharpest frame per motion segment, drops blur and held-still duplicates, keeps frames
on both sides of a cut, uses real presentation timestamps (variable frame rate), rejects a camera that barely moves. Summary now includes source frames,
sampled, kept, blurry, redundant, transitions, effective fps, source/extracted resolution, extraction seconds. `FRAME_SAMPLING=fixed` restores the old mode.

## 3. Test results
| Item | Result | Where / how |
|---|---|---|
| Python tests, runnable subset (72 tests) | **PASS** | Linux sandbox, 1 vCPU, no pytest/FastAPI/Open3D/PyTorch; run through a small pytest stand-in |
| COLMAP option names vs the real colmap.exe | **PASS** | every flag the code emits was found inside `colmap.exe` (byte search); does not prove per-command ownership |
| COLMAP command logic (22+18 tests, stand-in executable) | **PASS** | proves logic only |
| Frame extraction: room, static, blurry, corrupt, cut, uneven timestamps | **PASS** | synthetic videos |
| OpenCV camera poses on synthetic room video | **PASS** | 17 of 17 frames registered, 1,276 sparse points (`docs/acceptance_report_linux_sandbox_2026-11-05.json`) |
| Tour generation from real SfM poses (nodes, symmetric reachable graph, hotspots) | **PASS** | synthetic room, known poses |
| **colmap.exe starts / DLL loading / real feature extraction, matching, mapping** | **NOT TESTED** | Windows binary; cannot run on Linux |
| Open3D point cloud, TSDF mesh, Gaussian training | **NOT TESTED** | Open3D and PyTorch not installable here (no network). Tests skip. Gaussian training is the project's own CPU PyTorch rasterizer, not official 3DGS |
| FastAPI endpoint tests (`test_api`, `test_endpoints`) | **NOT TESTED** | FastAPI not installed here |
| Java compile / backend tests, Flyway on PostgreSQL | **NOT TESTED** | no Maven or PostgreSQL here |
| Frontend `tsc` / `next build` | **NOT TESTED** | no node_modules; frontend unchanged |
| PowerShell scripts | **NOT TESTED** | no PowerShell here; syntax unchecked, expect a first-run fix |
| Browser: Walkthrough and Digital Twin showing a real job | **NOT TESTED** | |
| Real property video | **NOT TESTED** | none supplied |

## 4. NOT done (be aware)
- **Java job state machine** (VALIDATING, FEATURE_EXTRACTION, ... RETRYING) and any Java/DB change: not touched because I cannot compile Java here and a broken backend is worse than the current statuses
  (QUEUED, PROCESSING, RECONSTRUCTING, CALIBRATING, GENERATING_MODEL, TRAINING_SPLAT, GENERATING_TOUR, COMPLETED, FAILED, CANCELLED). The AI service already reports a stage and percentage within them.
- COLMAP dense MVS (needs CUDA), texture mapping, doorway detection, UI changes (the new frame statistics and `/colmap/status` are available from the API; the page shows the fields it already knew).
- Bundle adjustment beyond the mapper's own; `build_bundle_adjuster` exists but is not wired into the job.
- Not verified: that the 1.0 `-h` output lists every option for the exact command that uses it. The service reads that help at run time and fails with a named option instead of guessing.

## 5. First run on your PC
`.\scripts\setup-all.ps1 -InstallVcRuntime` then `.\scripts\check-colmap.ps1`. If `check-colmap` fails, paste its output; that is the first real evidence for the bundled build.
Then `.\scripts\test-full-pipeline.ps1 -Full -Video C:\path\walkthrough.mp4`. Expect Gaussian training to be slow on the i5-1235U.


---
# Update 2 (2026-11-05): two independent modes (Pipeline A tour / Pipeline B advanced 3D)
See `docs/ARCHITECTURE_TWO_MODES.md`.

New: `viewpoints.py`, `POST /video/viewpoints`, `/colmap/status` health verdict (`not_installed`, `executable_missing`, `dll_missing`, `start_failed`, `unsupported_command`, `ok` + capability flags),
migration V4, `ProcessingService.runVideo` restructure, frontend guards, `scripts/check-all.ps1`, `scripts/test-pipeline.ps1`.
Also fixed: the blur filter compared each frame with the whole video's median, which discarded an entire plain room next to a textured one; it now uses the neighbouring +-2 s.

| Item | Result |
|---|---|
| Python tests, runnable subset: 80 pass | **PASS** (sandbox, stand-in runner) |
| Pipeline A on the synthetic room video with COLMAP absent: 17 viewpoints, 32 links, 13 drawn hotspots, validation passed | **PASS** (`docs/pipeline_a_sandbox_run_2026-11-05.json`) |
| Pipeline A: no poses claimed, neutral labels, timestamps kept, cut -> new area + unverified link, 360 -> no invented yaw, damaged frames refused, 3D stack not imported | **PASS** (8 tests) |
| Java: syntax parse of every source file | **PASS** (javac, only missing-dependency errors); **compile, run, Flyway V4 on PostgreSQL: NOT TESTED** |
| Job flow "tour published, then advanced 3D fails, tour still available" in Java | **NOT TESTED** (code written, cannot run Spring here) |
| Frontend edits (TourViewer, Twin3D, FloorPlanTab, ReconstructionStudio, types) | **NOT TESTED** (no tsc / next build here) |
| Upload / auth / restart recovery / browser walkthrough | **NOT TESTED** |
| Room-type recognition (kitchen, bedroom...) | **NOT IMPLEMENTED** deliberately (no model; labels are neutral) |
| Separate "Start Advanced 3D" button and job type | **NOT IMPLEMENTED**: advanced 3D runs automatically after the tour; it cannot block or remove it |
| Hotspot accuracy | **APPROXIMATE** (image-flow estimate, no calibration) |
