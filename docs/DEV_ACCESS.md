# Development access (skip login for local testing)

For testing on your own machine only. It lets you open the dashboard without signing in. It is **OFF by default** everywhere (`.env.example`, `scripts\start-backend.ps1`, `scripts\start-frontend.ps1` and the backend code). Normal use goes through `/register` and `/login`. Turn it on only deliberately with `DEV_ACCESS=true` in `.env`.

## What it does
- The frontend skips the redirect to `/login` whenever it runs under `next dev` (`NODE_ENV === "development"`). `/` redirects to `/dashboard`, a refresh on any dashboard route stays there, `/login` forwards to `/dashboard`, and the sign-out button is hidden. Network failures show a plain "Cannot reach the backend" message instead of "Failed to fetch".
- The backend gives requests that come from this machine the identity of an **existing** user, so projects, ownership checks and foreign keys work exactly as in normal use.
- A yellow bar on every page shows live status of **Java**, **Python** and **PostgreSQL** (click *Details* for versions, latency, user count and Python capabilities such as COLMAP).

## What it does not do
- It does not delete or change the login/registration pages, `/api/auth/*`, JWT issuing and validation, or password hashing. Signing in normally still works, and a valid token always wins over the bypass.
- It does not create users, hardcode tokens or return mock data. Every API call and every status value is real.
- It does not work in production: see "Safety layers".

## Enable
1. Set `DEV_ACCESS=true` in `.env` (or run `scripts\dev-access.ps1 on`).
2. If you changed it, **restart the backend and the frontend** (`scripts\stop-all.ps1`, then `scripts\start-all.ps1`). Both read the value only at start-up. Both scripts print a warning when it is on.
3. The bypass needs one real account to act as. If the database has no users yet, the status bar says so: open `/login`, use **Register** once, then reload. After that no login is needed again. To act as a specific account, set `DEV_ACCESS_EMAIL=you@example.com` (it must already exist); otherwise the oldest user is used.
4. Open http://localhost:3000.

Running by hand: set `DEV_ACCESS=true` in the shell before `mvn spring-boot:run` and before `npm run dev`.

## Disable
1. Set `DEV_ACCESS=false` in `.env` (or `scripts\dev-access.ps1 off`). Do not leave it empty or rely on a stale value: set it to `false`.
2. Restart backend and frontend.
3. Confirm: `scripts\dev-access.ps1 status` says OFF, the yellow bar is gone, and opening `/dashboard` in a private window sends you to `/login`. `GET http://localhost:8080/api/dev/status` answers only `{"devAccess":{"enabled":false}}`, and `GET /api/projects` without a token returns 401.

PowerShell tip: the scripts never override variables already set in the current window. `dev-access.ps1` clears its own copy, but if you set `$env:DEV_ACCESS` by hand, remove it (`Remove-Item Env:\DEV_ACCESS`) or open a new window.

## Safety layers
1. **Backend code defaults to off**: without the variable (e.g. a deployed jar), no bypass. The backend filter is not even added to the security chain unless `DEV_ACCESS=true`.
2. **Production refuses it**: the backend fails to start if `DEV_ACCESS=true` is combined with a `prod`, `production` or `staging` Spring profile. The frontend only honours it when `NODE_ENV === "development"`; `next build` / `next start` always ignore it and the dev code is stripped from the bundle (checked by searching the build output).
3. **Local requests only**: the backend ignores the bypass unless the connection comes from the loopback address, carries no proxy headers (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `X-Forwarded-Host`) and, if it has an `Origin` header, that origin is one of `CORS_ORIGINS` or the backend itself. A phone on your Wi-Fi, or another website open in your browser, gets normal authentication.
4. **Real users only**, no new accounts, no made-up tokens.
5. Loud warning in the backend log at start-up.

Consequences: using the app from another device (README, phone on Wi-Fi) needs a normal login. If you put a reverse proxy in front of the backend, the bypass turns itself off.
Never set `DEV_ACCESS=true` on a shared, staging or public machine, and never commit a `.env` that contains it.

## Checking the three services
```powershell
scripts\check-services.ps1
```
Tests each service on its own, without one vouching for another: PostgreSQL (port plus a real `psql` login and query), Python (`GET /health` with capabilities) and Java (`/actuator/health`). It exits non-zero if any is down. The yellow bar shows the backend's view of the same links (Java to PostgreSQL by SQL query, Java to Python by HTTP). If the backend itself is down, the bar shows Java as DOWN and Python/PostgreSQL as "unknown": the browser cannot call them directly. Use the script then.

## Testing the features
Start everything with `scripts\start-all.ps1`, open the dashboard and create a project.

| Feature | How to test | Needs |
|---|---|---|
| Image upload | Project page, upload a photo | Java, PostgreSQL, shared `data\storage` |
| Object detection | Press Analyze, open *Image intelligence* | Python capability `detection segmentation` (first run downloads YOLO weights; internet once) |
| Measurements | Same results; calibrate with a reference object; edit values | `metric depth` for estimates; calibration and manual values work without it |
| Video processing | Upload a video (`python scripts\make_test_video.py` makes a synthetic one) | Python; frame extraction needs no COLMAP |
| 3D reconstruction | Upload a real, slow, well-lit 1-3 min walkthrough and press Reconstruct | Python capability `colmap` must be yes |
| 360 navigation | Upload with the 360 option, then open *Virtual tour* | A successful reconstruction |

The yellow bar's *Details* shows which Python capabilities are available, so you can see up front why a step would fail. Capabilities the README lists as not implemented are still labelled as such in the UI; this change does not alter that.
