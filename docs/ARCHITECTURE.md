# Architecture notes

## Coordinate frames
COLMAP's world is arbitrary. `geometry.world_normalisation` builds a frame with +Y up (mean of the cameras' negative image-y axes), x along the scene's principal ground direction, z = x × up. Angles on the ground are `phi = atan2(z, x)`, which increases clockwise seen from above, matching Marzipano's yaw (positive to the right).

## Hotspots
- Flat video: neighbour camera centre projected through the viewing camera (pinhole, distortion ignored). In frame → pixel hotspot; otherwise only a bearing, listed as "not visible from here".
- 360: yaw = phi(B − A) − phi0, where phi0 is the world angle of the panorama's longitude 0, averaged over the four rendered faces.

## Shared storage
The backend and the AI service read and write the same folder (`STORAGE_ROOT`, default `<repo>\data\storage`). Only storage-relative paths with forward slashes cross the HTTP boundary, so the same values work on Windows and Linux.

## Job pipeline
`processing_jobs.status` is updated by `ProcessingService` before each AI call, so the SSE stream reflects the stage actually running. A failed AI call stores its message in `error`; `POST /jobs/{id}/retry` re-runs the whole job.

## Measurements
`measurement_records` is append-only. Current value = newest row per (object, kind). Statuses: ESTIMATED (model-derived), CALIBRATED (scaled from a user-supplied reference), VERIFIED (typed in by the user).


## Reconstruction pipeline modules (ai-service/app)

- `hardware.py`: runtime detection and CPU-only device choice (CPU threads, RAM, Intel GPU inventory, and a real Open3D CPU point-cloud smoke test). SYCL/XPU are neither probed nor selected. The AI health endpoint runs cached CPU smoke tests; model-backed flags require local weights and successful CPU inference.
- `jobs.py`: per-job progress, log and cancellation (events plus child-process termination).
- `video_pipeline.py`: frame sampling, blur/duplicate removal, RAM-aware resizing, thumbnails.
- `sfm.py`: OpenCV incremental SfM with self-calibration and bundle adjustment (used when COLMAP is absent); `reconstruct.py` picks the backend and writes poses and the sparse cloud.
- `dense.py`: Open3D point cloud, depth fitting, TSDF mesh, ICP helper.
- `splat.py`: PyTorch Gaussian trainer, PLY/SPLAT/SPZ writers and readers, Open3D render attempt.
- `report.py`: `work/report.json`, the single record of stage statuses, devices and output files that the backend and UI read.

Java: `ProcessingService` runs frames → poses → tour → point cloud and mesh → Gaussians, polls `/jobs/{id}/status` for progress, and changes job rows with targeted UPDATE statements so the worker and the poller cannot overwrite each other.
