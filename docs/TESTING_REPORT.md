# Testing report

## Validation performed

Validated on the Windows CPU environment for this project. The run did not install or use CUDA or Intel XPU.

| Check | Result | Details |
|---|---|---|
| AI-service tests | PASS, 102 passed | Full Python test suite, including CPU hardware, Open3D, COLMAP compatibility, dense mesh, Gaussian training and API tests |
| Backend tests | PASS, 12 passed | Maven test suite |
| Frontend typecheck | PASS | `npm run typecheck` |
| Frontend production build | PASS | `npm run build` |
| Open3D CPU capability | PASS | Open3D 0.20.0 imported; real CPU point-cloud operations and dense TSDF mesh smoke test passed |
| COLMAP CPU capability | PASS | Bundled COLMAP 4.2.1 started without GPU support; reconstruction commands explicitly use CPU |
| AI `/health` endpoint | PASS | Open3D, dense mesh, Gaussian, metric depth, COLMAP and OpenCV SfM true; XPU flags false; detection false because local YOLO weights are absent |

## Synthetic video route integration

No sample phone or user video was present, so a temporary, textured 24-frame MP4 fixture was generated and passed through the actual FastAPI routes. The video was placed in the AI service's storage directory; this validates the AI pipeline, not the Java/backend upload or database flow.

| Stage | Result |
|---|---|
| Adaptive frame extraction | 14 frames kept; 10 duplicates removed |
| Viewpoint extraction | 14 viewpoints |
| COLMAP CPU reconstruction | 14 of 14 images registered; 2,542 sparse points |
| Pose-based walkthrough | 10 connected tour nodes |
| Dense point cloud | 2,470 points; PLY read back with Open3D |
| Depth-fused mesh | 8,377 triangles; PLY read back with Open3D |
| CPU Gaussian training | 400 Gaussians; stage reported success |
| Stage report | COLMAP, camera poses, point cloud, mesh and Gaussian stages all reported `ok` |

The fixture exercises real frame extraction, bundled COLMAP, the locally available metric-depth model, Open3D CPU fusion, and PyTorch CPU optimization. Synthetic imagery does not establish accuracy or robustness on real indoor footage.

## Remaining unverified

| Check | Status / reason |
|---|---|
| Real photo/video reconstruction and measurement accuracy | NOT RUN; no real sample media was available |
| YOLO segmentation | NOT RUN; `yolov8m-seg.pt` is not present locally, so health truthfully reports `detection_segmentation: false`; no weights were downloaded |
| Live Java → AI upload/job → database persistence flow | NOT RUN; backend unit tests passed, but the live services and PostgreSQL migrations were not started/applied |
| Frontend viewer rendering | NOT RUN in a browser; typecheck and production build passed |
| Desktop/mobile walkthrough interaction | NOT RUN in a browser or emulator |
| PowerShell setup scripts | NOT RUN |
| Intel XPU / Open3D SYCL | Intentionally disabled and not tested or selected |
| Open3D/Vulkan Gaussian renderer | Intentionally skipped; the CPU pipeline uses the built-in CPU preview path |
| SPZ compatibility with Niantic's external loader | NOT RUN; project-local format tests are not external validation |

## Product limitations

- Viewpoint areas are not automatic semantic room classifications. Users create and assign rooms through the existing room workflow.
- Detected-object-to-room linking and automatic wall, door, and room-boundary detection are not implemented.
- Metric depth and fused geometry are estimates, not survey-grade measurements. Scale and quality depend on camera motion, texture, lighting, and the depth model.
- The Gaussian implementation is a compact CPU-capable preview trainer, not a CUDA-class, fully featured 3D Gaussian Splatting system. Its time and scene limits are configurable.
- A successful CPU capability smoke test proves that an operation runs; it does not promise useful latency on every 16 GB laptop or guarantee quality for arbitrary input.
