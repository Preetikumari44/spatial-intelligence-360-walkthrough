# Authentication testing report

**Read this first.** This revision was produced in a sandbox with no internet, no Java compiler or Maven, no PostgreSQL, no Windows and no browser. Your ten required tests therefore **could not be executed here**. They are not marked as passed. `scripts\test-auth.ps1` was written so you can run them in seconds against your running services.

## What was executed

| Check | Result |
|---|---|
| Frontend `tsc --noEmit` | PASS |
| Frontend `next build` (16 routes including `/login` and `/register`) | PASS |
| Java compile of the changed backend files | NOT RUN (no `javac`/Maven available) |
| `scripts\test-auth.ps1` | NOT RUN (written, never executed; PowerShell syntax unverified) |

## Your tests 1 to 10

| # | Test | Status | How to run it |
|---|---|---|---|
| 1 | Register a new account | NOT RUN | `scripts\test-auth.ps1` (step 1) or the `/register` page |
| 2 | Account saved in PostgreSQL (BCrypt hash) | NOT RUN | test-auth step 2 (needs `psql`) |
| 3 | Sign in with correct credentials | NOT RUN | test-auth step 3 |
| 4 | Wrong password rejected (401) | NOT RUN | test-auth step 4 |
| 5 | Duplicate email rejected (409) | NOT RUN | test-auth step 5 |
| 6 | Refresh keeps session valid | NOT RUN | script checks `/api/auth/me`; refreshing the dashboard in a browser must be tried by hand |
| 7 | Sign out, protected pages redirect to login | NOT RUN | script checks 401 without token; the redirect itself needs a browser |
| 8 | Java and Python connectivity | NOT RUN | test-auth step 8, or `scripts\check-services.ps1` |
| 9 | CORS and browser requests | NOT RUN | test-auth prints the CORS preflight result for `localhost` and `127.0.0.1`; also watch the browser Network tab |
| 10 | Image and video upload connectivity | NOT RUN | test-auth creates a project and calls the image upload endpoint; video upload must be tried by hand |

## "Failed to fetch": what was found and fixed

I could not reproduce the failure, so the exact cause on your machine is **unconfirmed**. I inspected the full path and fixed every defect found that produces exactly this symptom:

1. CORS only allowed the origins listed verbatim in `CORS_ORIGINS`. A trailing slash, stray spaces or opening the site on the other host form made the browser reject the response, shown only as "Failed to fetch". Origins are now normalised and the `localhost`/`127.0.0.1` twin of each is allowed.
2. CORS did not allow `PUT` (used by the room assignment added in the previous revision). Added `PUT` and `HEAD`, and a preflight cache.
3. The frontend discarded the real reason. The error now names the backend URL and the page origin, and both auth pages probe `/actuator/health` with a real cross-origin request and show the result.
4. Backend error handling: malformed JSON now returns 400 and unique-constraint races return 409 (previously a generic 500); validation messages name the field problem.

If it still fails after this, run `scripts\test-auth.ps1` and send me the first failing line.

## Other changes
- `/login` and `/register` rebuilt with show/hide password, confirm password, client-side validation and a working "Remember me" (localStorage vs sessionStorage).
- Registration returns 201 with a token and signs the user in; the frontend then opens `/dashboard`.
- `GET /api/auth/me` added; the app layout validates the session with it before showing any page.
- `DEV_ACCESS` is off by default (`.env.example`, `start-backend.ps1`, `start-frontend.ps1`, frontend flag now opt-in). No fake users or tokens exist anywhere.
- No database migration was needed: the existing `users` table is used.
