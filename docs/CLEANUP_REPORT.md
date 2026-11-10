# Fresh-start cleanup (2026-11-09)

Same project, same source. Only previously uploaded test data and its generated results were removed.

## Removed from the ZIP (backed up in Spatial-Intelligence-OLD-DATA-BACKUP.zip)
- `data/storage/projects/73c57491-...` (177 MB: 1 video, 1 photo, 9 jobs, 5,649 extracted frames, tour/panorama output, 6 COLMAP `database.db`, logs)
- `data/storage/projects/864da064-...` (56 MB: 1 video, 1 photo, 3 jobs, 807 frames, 1 COLMAP `database.db`, logs)
- `.run/` pid files and service logs (stale), `ai-service/.pytest_cache`, `frontend/.next/cache` (rebuilt automatically)
Details: `CLEANUP_MANIFEST_2026-11-09.md`.

## Kept untouched
Frontend, backend (incl. Flyway migrations V1-V5), AI service, `yolov8m-seg.pt`, `tools/colmap`, `.env`, `.env.example`, scripts, docs, auth/dev-access code.

## Storage layout
`data/storage/{projects,jobs,videos}` exist and are empty (`.gitkeep`). User uploads go to `projects/<id>/media`, processing output to `projects/<id>/jobs/<job>`. The backend and AI service create missing folders on demand.

## Database (NOT inside the ZIP)
Your PostgreSQL database lives on your machine, so its rows cannot be cleaned from the ZIP. Old projects still listed in the app come from there. Do this:
1. `scripts\stop-all.ps1`
2. `scripts\clean-demo-data.ps1` (report only: lists accounts, projects per owner, row counts, orphans)
3. Check the project list is really all test data, then `scripts\clean-demo-data.ps1 -Execute`
   (takes a `pg_dump` + storage backup into `backups\<timestamp>`, asks you to type CLEAN, deletes in one transaction, rolls back if anything would be orphaned).
   Keep a project with `-KeepProjects "<uuid>,<uuid>"`.
Users, schema, migrations and config are never touched. Alternative without scripts: sign in and delete each project in the app (this removes its rows and files).

## UI
Projects page shows "No projects yet" and each new project shows the upload cards with supported formats and size limits (added) plus job progress.

## Verification status
Tested here: both SQL scripts against PostgreSQL 16 built from your migrations (users kept, all project data removed, keep-list works, no orphans). Not run here: frontend, Spring Boot, AI service and COLMAP (Windows, no Node/Maven/COLMAP in the sandbox). Run `scripts\check-all.ps1` after starting.
