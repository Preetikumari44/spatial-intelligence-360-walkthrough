# Regeneration report: what changed, what was tested, what was NOT done

Read this first. It is deliberately blunt.

## 1. Audit (existing code, before changes)
| Area | State found |
|---|---|
| Spring Boot, JWT auth, ownership, projects, media upload, jobs (retry, cancel, SSE, logs), rooms, tour/navigation, reconstruction outputs, capabilities | Implemented |
| FastAPI service: frames, blur/duplicate filter, OpenCV SfM, Open3D cloud, TSDF mesh, PyTorch Gaussian trainer, job registry, report.json | Implemented, CPU-first |
| Frontend: Video Reconstruction, 3D Digital Twin, Walkthrough (Marzipano), Spatial Map (assign frames to rooms, remove wrong links) | Implemented |
| **COLMAP integration** | **Broken for COLMAP 4.x**: `--SiftExtraction.use_gpu`, `--SiftMatching.use_gpu`, `--SiftExtraction.max_image_size` are hard-coded |
| **Memory guard** | **Too strict**: refused to start below 3300 MB free; no adaptive plan, no OOM retry |
| **.env.example** | **Bug**: inline comments on values (`CPU_THREADS=0   # ...`). The PowerShell loader copied the comment into the value, so `int()` in config.py would crash |
| Automatic room detection; create doorway/connection; move hotspot; publish | **Missing** (backend has no POST connection, no publish flag, no hotspot move; no room classifier) |
| Maven build, PostgreSQL migrations, PowerShell scripts | Never executed by me (see section 4) |

## 2. Changes made
**New files**
- `ai-service/app/colmap_compat.py`: probes `colmap help` and `<command> -h`, builds commands only from options the binary lists, forces CPU, raises `ColmapCompatError` (HTTP 501) naming the command, the spellings tried and similar options if a required one is missing; optional options are skipped and recorded.
- `ai-service/app/memory_plan.py`: tiers normal / low / minimal from free RAM (`LOW_MEMORY_MODE` can force one), even frame subsampling that keeps timestamps, refusal with advice below `MIN_FREE_RAM_MB`.
- `ai-service/tests/test_colmap_compat.py`: 22 tests.
- `ai-service/tools/cpu_acceptance.py`, `scripts/test-cpu-pipeline.ps1`: the mandatory CPU acceptance run (installed / initialized / tested / generated, reported separately; exit 0 only if everything generated).
- `docs/backup/reconstruct.py.orig`, `docs/acceptance_report_linux_sandbox.json`, this file.

**Modified files**
- `ai-service/app/reconstruct.py`: uses the compat layer; adaptive plan; memory check before every COLMAP stage; exactly one automatic retry with a smaller plan on out-of-memory (exit codes 137 / 0xC0000005 / `bad_alloc`), then a loud failure; temp image copies always deleted; stale database and model removed on retry; exit codes now included in errors; chosen plan, flags used and flags skipped written to `report.json`.
- `ai-service/app/config.py`: `LOW_MEMORY_MODE`, `MEMORY_NORMAL_MB`, `MEMORY_LOW_MB`, `MIN_FREE_RAM_MB`.
- `.env.example`: no inline comments, new variables.
- `scripts/_common.ps1`: loader strips a stray trailing ` # comment` from unquoted values.
- Removed from the ZIP: `data/storage/videos/*.mp4` and `data/storage/jobs/t1` (leftover test fixtures that no database row refers to), `node_modules`, `.next`, caches.

**Database**: no migration added (none was needed for these changes). Existing V1 to V3 untouched.

## 3. COLMAP compatibility
Spellings used, newest first: `FeatureExtraction.use_gpu` (then `SiftExtraction.use_gpu`), `FeatureExtraction.max_image_size`, `FeatureMatching.use_gpu`, optional `SiftExtraction.max_num_features`, `*.num_threads`, `SequentialMatching.overlap`, `Mapper.num_threads`, `Mapper.ba_use_gpu`. The new names were cross-checked against the option classes of **pycolmap 4.2.1**, but **not against the real `colmap.exe -h` on your machine**; the binary's own help is read at run time, and `tools/cpu_acceptance.py` prints what it found.

## 4. Test results (executed in a Linux sandbox: 1 vCPU, 3 GB RAM, no GPU)
| Check | Result |
|---|---|
| AI service pytest | **55 passed, 1 skipped** (33 existing + 22 new). Skipped: Gaussian test, PyTorch not installed here |
| COLMAP command tests | Pass, using a stand-in executable that prints 4.x-style and 3.x-style help. Proves the logic, **not** that real COLMAP accepts the flags |
| Real COLMAP 4.2.1 on CPU | Ran through the **pycolmap library** on 20 synthetic room frames: all 20 registered, 3,251 sparse points, about 42 s. This is the library, **not** `colmap.exe`, and synthetic, **not** your video |
| Acceptance harness on a synthetic video (Linux) | Open3D point cloud: installed, initialized, tested, **generated** (1,686 points reloaded and filtered). COLMAP: not installed here. Mesh: **unavailable** (no `transformers`/depth model here). Gaussian splat: **unavailable** (no PyTorch here). Camera poses came from the OpenCV fallback |
| Frontend `tsc --noEmit`, `next build` | Pass (unchanged frontend) |
| Maven build and tests, Flyway on PostgreSQL | **NOT RUN** (Maven Central unreachable from the sandbox, no PostgreSQL) |
| PowerShell scripts, Windows, Intel Iris Xe | **NOT RUN** |
| Browser viewer rendering real output | **NOT RUN** |
| Login/registration end-to-end | **NOT RUN** (code untouched) |
| Real phone video end to end | **NOT RUN** |

## 5. NOT done (requested but not delivered)
Automatic room classification; scene-editor additions (create doorway/connection, move hotspot, edit camera node position, publish) and their Java endpoints; a new Walkthrough/Digital Twin UI; Java or database changes. I could not compile Java, and adding backend code I cannot compile would risk breaking a backend that currently works. The existing Spatial Map page still covers room creation, frame assignment and wrong-link removal.

## 6. Run the mandatory CPU acceptance on your PC
```
.\scripts\setup-ai.ps1          # once
.\scripts\test-ai.ps1           # unit tests
.\scripts\test-cpu-pipeline.ps1 -Video C:\path\to\house.mp4
```
Paste the printed table and `acceptance_report.json` back to me; that is the evidence for COLMAP CPU, Open3D mesh and Gaussian CPU. Expect Gaussian training to be slow on an i5-1235U; a result of "unavailable" or "failed" is reported as such and is not an error in the harness.

## 7. Low RAM
With about 3 GB free the job now runs in the **low** plan (720 px, up to 60 frames, 2 threads); below 2800 MB free it uses **minimal** (512 px, 36 frames, 1 thread). Under 1200 MB it refuses with advice. If it still fails: close the browser, set `LOW_MEMORY_MODE=minimal` and `FRAME_TARGET_FPS=1`, restart the AI service, re-upload. The tier thresholds are heuristics, not measurements.

## 8. Recording tips
Walk slowly, hold the phone landscape, one smooth pass per room, keep furniture and door frames in view, avoid blank walls and mirrors, good light, no fast turns, pause 1 second at each doorway, 1 to 2 minutes total. See `docs/CAPTURE_GUIDE.md`.
