# Spatial Intelligence Platform (native Windows edition)

## Quick start on Windows 11 (native, no Docker)

```powershell
# once (prerequisites: JDK 21, Maven, Node 20, Python 3.11, PostgreSQL; see the table below)
.\scripts\setup-all.ps1 -InstallVcRuntime     # .env + random JWT secret, COLMAP check, DB, Python env, Maven, npm
# every time
.\scripts\start-all.ps1                       # PostgreSQL -> AI service -> backend -> frontend, each health-checked
.\scripts\check-colmap.ps1                    # COLMAP starts? version? options present?
.\scripts\test-full-pipeline.ps1 -Full        # PASS / FAIL / NOT TESTED per item
.\scripts\stop-all.ps1
```
Two modes: the **Virtual Walkthrough** is built from your video frames alone and opens as soon as it is validated; COLMAP / 3D is an optional second stage that can fail without affecting it (see docs/ARCHITECTURE_TWO_MODES.md).
URLs: app http://localhost:3000, backend http://localhost:8080/swagger-ui.html, AI service http://localhost:8000/health and /colmap/status.
setup-all asks for the database password if `DB_PASSWORD` is empty; it never invents one and never overwrites an existing `.env` value.

Photo object detection and measurement, plus video-to-3D reconstruction with a navigable virtual tour.
This version runs directly on Windows 10/11. It does not use Docker, Docker Desktop or containers.

| Part | Technology | Port |
|---|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind, Three.js / React Three Fiber, Marzipano | 3000 |
| Backend | Java 21, Spring Boot 3, Spring Security (JWT), Flyway | 8080 |
| AI service | Python 3.11, FastAPI/Uvicorn, PyTorch, OpenCV, YOLO, COLMAP | 8000 |
| Database | PostgreSQL 16 (local Windows service) | 5432 |

```
Browser ──> Next.js :3000 ──REST/SSE──> Spring Boot :8080 ──HTTP──> FastAPI :8000 ──> COLMAP / YOLO / depth
                                            │                              │
                                       PostgreSQL :5432          shared folder  data\storage
```
The backend owns users, projects, jobs, measurements and the tour graph. The AI service does all vision and geometry. They share one folder, `STORAGE_ROOT` (default `<repo>\data\storage`), and exchange only small JSON and storage-relative paths.

## Status: read this first

**Panoramas (2026-11-08)**: `/video/panoramas` stitches real panoramas where several frames share one camera position, labelled `full_sphere` / `horizontal_360` / `partial` with coverage and seam error; `/video/sensors` reports GPS/motion metadata. Not yet wired into the jobs or the viewer: see [docs/PANORAMA_AND_SENSORS.md](docs/PANORAMA_AND_SENSORS.md).

**Viewpoint links (2026-11-08)**: viewpoints are now linked only when the reconstruction proves they see the same features (shared 3D landmarks for the pose-based tour; essential-matrix / homography verification for the no-COLMAP tour). Video order and camera distance alone no longer create links; stretches that do not connect are reported and left out. See [docs/VIEWPOINT_CONNECTION_FIX.md](docs/VIEWPOINT_CONNECTION_FIX.md) for the root cause, tests run and what was not verified (COLMAP, Java/PostgreSQL and the frontend were not run in that session).


**Authentication (latest revision)**: normal sign-in is the default. Open http://localhost:3000, you land on `/login` (redirected from `/dashboard`); create an account on `/register` (full name, email, password, confirm password), which signs you in and opens the dashboard. Sessions are validated against `GET /api/auth/me` on every page load; an invalid or expired token sends you back to `/login`, and a stopped backend shows a retryable error instead of logging you out. "Remember me" keeps the token in localStorage (survives closing the browser); unticked, it is kept in sessionStorage (cleared when the tab closes). `DEV_ACCESS` is **off** by default in `.env.example`, both start scripts and the code. Run `scripts\test-auth.ps1` against your running services to execute the authentication checks for real (register, BCrypt row in PostgreSQL, login, wrong password, duplicate email, `/me`, 401s, CORS preflight, project and image upload calls). See [docs/AUTH_TESTING_REPORT.md](docs/AUTH_TESTING_REPORT.md).

**Implemented**: JWT auth with roles, ownership checks, private media (no public URLs), async jobs with live status (SSE) and retry, automatic video-reconstruction queueing after successful upload validation, photo analysis (YOLOv8 segmentation when local weights are available, plus metric depth), reference calibration, append-only measurement history (ESTIMATED / CALIBRATED / VERIFIED), video validation, frame extraction with blur/duplicate removal, CPU COLMAP reconstruction, CPU point-cloud and depth-fused mesh generation, CPU Gaussian training, tour viewpoints and hotspots (flat and 360° video), coverage reporting, floor-plan point map, 3D point-cloud view, CSV export, light/dark theme, PWA manifest.

Video uploads accept MP4, MOV, AVI, WebM and MKV containers. A video is accepted for reconstruction only if the installed OpenCV decoder can open it and read a frame; codec support can vary by machine.

**Dashboard**: sidebar sections Overview, Projects, Image Intelligence, Video Reconstruction, Spatial Map, 3D Digital Twin, Virtual Walkthrough, Object Inventory, Measurements, Settings. Each section page has a project picker and shows real data from the API. The service-status strip was removed from every page; Java / PostgreSQL / Python / frontend health is now under **Settings → System Diagnostics**, with full error text. Projects can be renamed (`PATCH /api/projects/{id}`) and deleted with an inline confirmation. Overview shows real counts and processing history.

**Spatial map and rooms (latest revision)**: rooms are created and confirmed by the user (database table `rooms`, migration `V2__rooms.sql`, `navigation_nodes.room_id`). On the Spatial Map you select a viewpoint, create a room from it, assign more viewpoints, click a room to enter it, remove a wrong doorway link, and zoom/pan/reset the map. Viewpoints are coloured and labelled by room; the walkthrough shows the room name, a Back button with a navigation trail, Back to floor plan, and a room-aware mini-map. The current viewpoint is kept when you switch sections. Re-running reconstruction replaces the viewpoints, so room assignments must be redone (rooms themselves are kept).

**Not implemented** (labelled in the UI): textured mesh (the mesh has vertex colours only), SAM 2, automatic wall/door/window/room detection and room boundary polygons (rooms are manual groupings of viewpoints; there is no vector floor plan), adding doorway links by hand, multi-floor selector, linking video objects to rooms, room areas and ceiling height, detection of non-COCO objects (doors, windows, wardrobes) by the default model, multi-video or multi-photo reconstruction, first-person 3D walkthrough, PDF reports, Redis, RabbitMQ, object storage (a local folder is used), malware scanning.

**Tested**: see [docs/TESTING_REPORT.md](docs/TESTING_REPORT.md) for the full record. On Windows CPU, the AI-service suite passed (102 tests), backend Maven tests passed (12 tests), and frontend typecheck and production build passed. A generated textured MP4 was run through the FastAPI frame, viewpoint, COLMAP, tour, depth-fusion, mesh and Gaussian stages: 14/14 frames registered, 2,542 sparse points, an 8,377-triangle mesh and 400 CPU-trained Gaussians were produced. `/health` confirmed CPU capabilities and reported XPU false.
**Still unverified**: no real user/phone video or image was available; the generated fixture does not establish reconstruction or measurement accuracy on real scenes. The local YOLO segmentation weights are absent, so `detection_segmentation` correctly reports false until weights are installed and actual CPU inference succeeds. The live Java/PostgreSQL-to-AI upload/job flow, migrations, PowerShell setup scripts, and desktop/mobile browser rendering were not exercised. Measurement accuracy has not been validated; the "reliability" value is a documented heuristic, not a probability. Hotspot orientation should be checked on a real walkthrough.

## 1. Prerequisites

Install these once. After installing anything that changes PATH, open a **new** PowerShell window.

| Software | Version | Notes |
|---|---|---|
| PostgreSQL | 16 (14+ works) | https://www.postgresql.org/download/windows/ . Keep port 5432, remember the `postgres` password, keep "Command Line Tools" ticked so `psql` is installed. |
| JDK | 21 | e.g. Eclipse Temurin 21. Set `JAVA_HOME`, check with `java -version`. |
| Apache Maven | 3.9+ | Unzip, add `bin` to PATH, check with `mvn -v`. |
| Node.js | 20 LTS | Includes npm. |
| Python | 3.11 (3.10–3.12 work) | Tick "Add python.exe to PATH". |
| COLMAP | bundled | **Included** in `tools\colmap\bin` (COLMAP 4.2.1, CPU/no-GPU build, all DLLs). Nothing to put on PATH: the AI service adds that folder itself. `COLMAP_BIN` is only an optional override. It needs the **Microsoft Visual C++ 2015-2022 x64 runtime** (not inside the COLMAP package): `scripts\install-colmap.ps1 -InstallVcRuntime` (admin) installs it. |
| Git (optional) | | |

## 2. First-time setup

Open PowerShell in the project folder.

```powershell
# allow the project's scripts in this window only
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 1. configuration
Copy-Item .env.example .env
notepad .env          # set DB_PASSWORD and JWT_SECRET (32+ characters)
```
Generate a JWT secret:
```powershell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }) -as [byte[]])
```

```powershell
# 2. database: creates role + database only if they are missing, never drops anything
scripts\start-database.ps1        # starts the PostgreSQL service if it is stopped
scripts\create-database.ps1       # asks for the 'postgres' superuser password once

# 3. Python environment (several GB: PyTorch, Ultralytics, transformers)
scripts\setup-ai.ps1
```
For an NVIDIA GPU, install the CUDA build of PyTorch from pytorch.org into `ai-service\.venv` after `setup-ai.ps1`, and set `COLMAP_USE_GPU=1` only with a CUDA build of COLMAP.

The frontend installs its packages on first start; the backend downloads Maven dependencies on first start. The first photo analysis downloads the YOLO weights and the depth model (internet needed once).

## 3. Start and stop

```powershell
scripts\start-all.ps1      # database -> AI service -> backend -> frontend
scripts\stop-all.ps1       # stops only what the scripts started
```
Open http://localhost:3000, register an account, create a project and upload.

For local testing without logging in, see [docs/DEV_ACCESS.md](docs/DEV_ACCESS.md) (`DEV_ACCESS=true`, off by default, never for shared or production use). `scripts\check-services.ps1` tests PostgreSQL, Python and Java independently.

Individual scripts: `start-database.ps1`, `start-ai.ps1`, `start-backend.ps1`, `start-frontend.ps1`. Each checks its prerequisites and port, refuses to start a second copy, and waits until the service answers. Logs are in `.run\logs\`. `stop-all.ps1` never stops the PostgreSQL service or any program it did not start.

Running by hand instead of the scripts (load the values from `.env` into your shell first):
```powershell
cd backend;    mvn spring-boot:run
cd ai-service; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd frontend;   npm install; npm run dev
```
Defaults are `localhost` for PostgreSQL and the AI service, `http://localhost:8080` for the frontend's API base, and CORS for `http://localhost:3000`.

## 4. Configuration (`.env` in the repository root)

| Variable | Default | Purpose |
|---|---|---|
| `DB_URL` | `jdbc:postgresql://localhost:5432/spatial` | JDBC URL of the local database |
| `DB_USER` / `DB_PASSWORD` | `spatial` / (required) | database login |
| `JWT_SECRET` | (required, 32+ chars) | token signing key; the backend refuses to start without it |
| `STORAGE_ROOT` | `<repo>\data\storage` | folder shared by backend and AI service |
| `BACKEND_PORT`, `AI_PORT`, `FRONTEND_PORT` | 8080, 8000, 3000 | ports |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | allowed browser origins |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8080` | API base used by the browser |
| `AI_SERVICE_URL` | `http://localhost:8000` | how the backend reaches Python |
| `XPU_MODE` | `0` | CPU-only execution; the AI service does not probe or select Intel XPU |
| `YOLO_MODEL`, `DEPTH_ENABLED`, `DEPTH_MODEL` | see `.env.example` | AI models |
| `COLMAP_BIN`, `COLMAP_USE_GPU` | empty (bundled), `0` | Empty = `tools\colmap\bin\colmap.exe`; a full path overrides it. GPU is always off for this build |
| `FRAME_SAMPLING`, `FRAME_MOTION_TARGET`, `FRAME_STATIC_MIN_MOTION` | `adaptive`, `0.05`, `0.25` | Motion-adaptive frame selection (see docs/COLMAP_INTEGRATION_REPORT.md) |
| `DEV_ACCESS`, `DEV_ACCESS_EMAIL` | `false`, empty | local-testing login bypass; see docs/DEV_ACCESS.md |

Use forward slashes or normal Windows paths for `STORAGE_ROOT`; both work. To use the app from a phone on the same Wi-Fi, set `NEXT_PUBLIC_API_URL` to `http://<PC-IP>:8080`, add `http://<PC-IP>:3000` to `CORS_ORIGINS`, and allow ports 3000 and 8080 in Windows Firewall.

### Existing data
The Flyway migration `V1__init.sql` creates the tables only in an empty schema. An existing database that already contains these tables is adopted (`baseline-on-migrate`), not recreated, and no script drops or truncates anything. To move data from an old setup, restore a `pg_dump` into the local database with `psql` before the first backend start, and copy the old media folder into `data\storage` (paths are stored relative to it).

## 5. API (full contract at http://localhost:8080/swagger-ui.html)

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/register` (201 + token; 400 invalid, 409 duplicate email), `POST /api/auth/login` (200 + token; 401 wrong credentials), `GET /api/auth/me` (200 profile; 401 without a valid token) |
| Dev status | `GET /api/dev/status` (only answers details when `DEV_ACCESS=true`, from this machine) |
| Projects | `POST/GET /api/projects`, `GET/PATCH/DELETE /api/projects/{id}` |
| Media | `POST /api/projects/{id}/images` (multipart `files`), `POST /api/projects/{id}/videos` (`file`, `is360`), `GET /api/projects/{id}/media`, `GET /api/media/{id}`, `GET /api/media/{id}/content`, `GET /api/projects/{id}/files?path=` |
| Jobs | `POST /api/ai/image-analysis`, `POST /api/ai/video-reconstruction` (`{projectId, mediaId}`), `GET /api/jobs/{id}`, `GET /api/projects/{id}/jobs`, `POST /api/jobs/{id}/retry`, `GET /api/jobs/{id}/events` (SSE) |
| Objects | `GET /api/projects/{id}/objects[?mediaId=]`, `PATCH /api/objects/{id}`, `GET /api/objects/{id}/measurements` |
| Rooms | `GET/POST /api/projects/{id}/rooms` (`{name, kind}`), `PATCH/DELETE /api/rooms/{id}`, `PUT /api/nodes/{id}/room` (`{roomId}` or null) |
| Connections | `DELETE /api/connections/{id}` (remove a wrong doorway link) |
| Tour | `GET /api/projects/{id}/tour` (now also returns `rooms`), `GET /api/tours/{id}/navigation` (tour id = project id), `PATCH /api/nodes/{id}` |
| Measurements | `GET /api/projects/{id}/measurements[?history=true]`, `PATCH /api/measurements/{id}`, `POST /api/projects/{id}/calibration/image`, `POST /api/projects/{id}/calibration/video` |
| Reports | `GET /api/projects/{id}/reports/inventory.csv` |
| Admin | `GET /api/admin/users` (ADMIN) |

Make an admin: `psql -U postgres -d spatial -c "update users set role='ADMIN' where email='you@example.com'"`.

## 6. Verifying the install (smoke tests)

1. `scripts\start-database.ps1` prints "Database 'spatial' accepts user 'spatial'".
2. `scripts\start-backend.ps1` ends with "Backend is up"; `http://localhost:8080/actuator/health` returns `UP`.
3. `scripts\start-ai.ps1` lists capabilities; `colmap` is true only if COLMAP was found.
4. `scripts\start-frontend.ps1` ends with "Frontend is up".
5. Register, sign out, sign in again (`/login`). Check Settings → System Diagnostics shows every service connected.
6. Create a project, upload a phone photo, press Analyze, open "Image intelligence".
7. Upload a short real walkthrough video (1–3 min, slow, well lit, overlapping views), press Reconstruct, watch the job status, then open "Virtual tour".
8. Backend → Python link: if step 6 produces objects, Java reached Python and Python read the uploaded file.
9. `cd ai-service; .\.venv\Scripts\python.exe -m pytest` runs the AI unit tests; `cd backend; mvn test` runs the Java ones.
10. `python scripts\make_test_video.py` writes a synthetic video for exercising upload and frame selection (COLMAP rightly cannot build a tour from it).

## 7. Troubleshooting

**"Failed to fetch" / "Cannot reach the backend" on Register or Sign in.** The browser blocked or could not complete the request. The login and register pages now show a live line under the form (reachable / not reachable). Causes, in order of likelihood: (1) the backend is not running or is on another port, check `http://localhost:8080/actuator/health` in the browser; (2) the page origin is not in `CORS_ORIGINS` (open the site exactly as `http://localhost:3000` or `http://127.0.0.1:3000`; the backend now also allows the localhost/127.0.0.1 twin of every configured origin and ignores trailing slashes); (3) `NEXT_PUBLIC_API_URL` points somewhere else: restart the frontend after editing `.env`; (4) a browser extension or firewall. Run `scripts\test-auth.ps1`: its CORS lines print the exact `Access-Control-Allow-Origin` the backend returns. Also note that the backend previously did not allow `PUT` in CORS, so the room-assignment call from the Spatial Map would fail with the same message; this is fixed.

| Symptom | Fix |
|---|---|
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, or run `powershell -ExecutionPolicy Bypass -File scripts\start-all.ps1`. |
| Could not start the PostgreSQL service | Run PowerShell as Administrator once, or start the service from `services.msc`. |
| `password authentication failed for user "spatial"` | `DB_PASSWORD` in `.env` differs from the role's password. Change one of them (`ALTER ROLE spatial PASSWORD '...'` as `postgres`). |
| `database "spatial" does not exist` | Run `scripts\create-database.ps1`. |
| Backend: `JWT_SECRET must be set and at least 32 bytes` | Fill `JWT_SECRET` in `.env`. |
| Backend: `Port 8080 is already used` | Another program holds it; close it or change `BACKEND_PORT` and `NEXT_PUBLIC_API_URL`. |
| Backend fails on first start | Check `.run\logs\backend.err.log` and `.out.log`. Maven needs internet the first time. |
| Browser: CORS error or "Failed to fetch" | Backend not running, or the page origin is missing from `CORS_ORIGINS`. Restart the backend after editing `.env`. |
| Login screen loops | Token expired or `JWT_SECRET` changed; sign in again. |
| Job fails: `AI service unreachable` | Start the AI service; check `AI_SERVICE_URL`. |
| Job fails: `COLMAP was not found` | Run `scripts\install-colmap.ps1`, then `scripts\check-colmap.ps1`. |
| `could not start ... 0xC0000135` | The Visual C++ runtime is missing: `scripts\install-colmap.ps1 -InstallVcRuntime` (admin PowerShell). |
| Job fails: `registered only N of M images` | The footage does not overlap enough. Film slower, keep textured objects in view, avoid blank walls and dim light. |
| First photo analysis is slow or fails offline | It downloads model weights once. With `DEPTH_ENABLED=0` photos are detected but not measured. |
| `pip` fails building a package | Use Python 3.11 (not 3.13) and rerun `scripts\setup-ai.ps1`. |
| `npm install` errors | Use Node 20 LTS; delete `frontend\node_modules` and run `scripts\start-frontend.ps1` again. |
| A script says a port is in use but nothing seems to run | `Get-NetTCPConnection -LocalPort 8080 -State Listen` shows the owning process id. |
| Leftover processes after a crash | `scripts\stop-all.ps1`; if a stale `.run\*.pid` exists it is cleaned automatically. |

## 8. Security notes
- Secrets live in `.env` (not committed). The AI service listens on 127.0.0.1 only.
- Uploads are limited by extension and size; unreadable videos are rejected at upload. There is no malware scanning.
- The JWT is kept in `localStorage`; before exposing this beyond your machine, add HTTPS and a Content-Security-Policy.
- The SSE endpoint accepts the token as a query parameter because browsers cannot set headers on EventSource; this is limited to that one path.


## 9. Intel CPU / Iris Xe reconstruction pipeline (new)

Video → 3D now runs without CUDA or an NVIDIA GPU, on a laptop such as an Intel Core i5 with Iris Xe graphics and about 16 GB RAM.

**Install (Windows PowerShell, from the repository root)**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
Copy-Item .env.example .env            # first time only; then fill in DB_PASSWORD and JWT_SECRET
.\scripts\setup-ai.ps1                 # CPU PyTorch + standard Open3D wheel: works on any Intel laptop
.\scripts\check-hardware.ps1           # shows what was detected and which device each stage will use
.\scripts\test-ai.ps1                  # optional, 2-5 minutes: runs the AI-service tests
.\scripts\start-all.ps1
```

Optional Intel acceleration (try it only after the CPU path works):

```powershell
.\scripts\setup-ai.ps1                 # installs CPU-only PyTorch and standard Open3D
.\scripts\check-hardware.ps1           # verifies CPU Open3D point-cloud and runtime status
```

**Pipeline and what each stage really does**

| Stage | Implementation | Device |
|---|---|---|
| Frame extraction | OpenCV; sampling by `FRAME_TARGET_FPS`, blur and near-duplicate removal, image size capped by free RAM, timestamps kept, thumbnails and a contact sheet written, at least `MIN_FRAMES` required | CPU |
| Camera poses | COLMAP (CPU only, `use_gpu=0`) if found; otherwise the built-in OpenCV pipeline: SIFT, sequential matching, focal-length self-calibration, two-view initialisation, PnP registration, SciPy bundle adjustment. 360° video needs COLMAP and is refused otherwise | CPU |
| Point cloud | Sparse SfM points → outlier removal → normals (Open3D tensor ops) → `pointcloud.ply` | CPU |
| Mesh | Monocular depth (`DEPTH_MODEL`) fitted per frame to the SfM points, fused with Open3D `VoxelBlockGrid` TSDF → `mesh.ply`, `mesh.obj`, `pointcloud_dense.ply` | CPU |
| Gaussian splats | A small PyTorch trainer (photometric loss, Adam, held-out views, PSNR before/after in the report) → `gaussians.ply`, `.splat`, `.spz` | CPU |
| Gaussian render | Built-in differentiable rasteriser renders the preview; the optional Open3D/Vulkan renderer is not invoked | CPU |

Every stage writes its status (`ok`, `failed`, `unavailable`, `skipped`), the device it really used and its output files to `work/report.json`; the Video Reconstruction page and `GET /api/projects/{id}/reconstruction/outputs` read that file. A failed or unavailable optional stage never turns into fake output: the job message says "Completed with limitations: mesh unavailable (...)" and the page shows the same text. If camera poses cannot be recovered, the job fails.

**Jobs**: `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry` (failed or cancelled), `GET /api/jobs/{id}/logs`, `progress` (0-100) on every job, `GET /api/ai/capabilities`. One job runs at a time (`JOB_CONCURRENCY=1`, and the AI service serialises heavy work too). Existing endpoints and fields are unchanged; new fields and the statuses `GENERATING_MODEL`, `TRAINING_SPLAT`, `CANCELLED` are additions. Run migration `V3__job_progress_cancel.sql` (Flyway applies it on backend start).

**Honest limits**

- The OpenCV pose estimator has no lens-distortion model, no loop closure and an arbitrary scale; COLMAP is more accurate. Film slowly with sideways movement and textured surfaces.
- Mesh depth is monocular and only scale-fitted to the SfM points: shapes are approximate, not survey-grade. It needs the depth model (first run downloads it) and PyTorch; without them the mesh stage reports `unavailable`.
- The Gaussian trainer is a compact, dense, low-resolution implementation (default 128 px, 4000 Gaussians, 300 iterations, no adaptive densification). It produces a preview-quality model, not a CUDA-class 3DGS result, and it stops at `SPLAT_TIME_BUDGET_SEC` (the report says how many iterations ran). CUDA-only gsplat is not used. The optional Open3D/Vulkan renderer is intentionally skipped in CPU-only mode.
- SPZ output is written from the published layout and round-trip tested with the project's own reader, not against Niantic's loader: check it in your viewer. `.ply` and `.splat` are the safe formats.
- This project is locked to CPU execution: the setup scripts install CPU-only PyTorch, Open3D SYCL / PyTorch XPU are not probed or selected, and the health endpoint reports both XPU capabilities as false.
- 360° video: COLMAP poses and the tour work as before; mesh and Gaussian stages are flat-video only.
- Tuning for a slow machine: lower `FRAME_TARGET_FPS`, `SFM_MAX_IMAGES`, `SPLAT_MAX_SIDE`, `SPLAT_ITERATIONS`, `DENSE_MAX_FRAMES`. Start with a 20-40 second video.
- Optional camera calibration: `python scripts\calibrate_camera.py --images "C:\calib\*.jpg" --pattern 9x6 --square-mm 25 --out camera.json`, then set `CAMERA_INTRINSICS_FILE`.
