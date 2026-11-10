import type { Job } from "./types";

const DEV_ACCESS = process.env.NODE_ENV === "development" && process.env.NEXT_PUBLIC_DEV_ACCESS === "true"; // OFF unless NEXT_PUBLIC_DEV_ACCESS=true under `next dev`; always false in production builds

export const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

const TOKEN_KEY = "token";

/** The session token lives in localStorage when "Remember me" was ticked, otherwise in sessionStorage (gone when the tab closes). */
export const getToken = () =>
  typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY) ?? sessionStorage.getItem(TOKEN_KEY);

export function saveToken(token: string, remember: boolean) {
  clearToken();
  (remember ? localStorage : sessionStorage).setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function authHeaders(init?: RequestInit) {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

async function check(res: Response) {
  // With development access on, a 401 means the backend has no user to act as; show that instead of bouncing to /login.
  if (res.status === 401 && DEV_ACCESS) {
    throw new ApiError(401, "The backend did not grant local access. Open Settings → System Diagnostics: the backend must run with "
      + "DEV_ACCESS=true and the database needs one existing user account to act as.");
  }
  // An expired or invalid session on a protected call sends the user to sign in again. Failed sign-in attempts
  // themselves (/api/auth/*) are shown on the form instead.
  if (res.status === 401 && typeof window !== "undefined" && !res.url.includes("/api/auth/")
      && !/^\/(login|register)/.test(window.location.pathname)) {
    clearToken();
    window.location.href = "/login";
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.message ?? body.detail ?? message;
      if (res.status >= 500) message = `${message} (server error ${res.status}; see the backend log)`;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

/** fetch() that explains a network failure instead of surfacing the browser's bare "Failed to fetch". */
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(BASE + path, init);
  } catch {
    const here = typeof window === "undefined" ? "" : window.location.origin;
    throw new ApiError(0, `Cannot reach the backend at ${BASE} from ${here}. Either it is not running, or it rejected this origin (CORS): `
      + `CORS_ORIGINS must include ${here}. Run scripts\\test-auth.ps1 to see which.`);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await check(await send(path, { ...init, headers: authHeaders(init) }));
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Private media needs the Authorization header, which <img> cannot send, so fetch it as a blob. */
export async function blobUrl(path: string): Promise<string> {
  const res = await check(await send(path, { headers: authHeaders() }));
  return URL.createObjectURL(await res.blob());
}

/** Raw bytes of a private file (PLY, .splat, ...). Fetched with the session token because <a>/<img> cannot send it. */
export async function fetchBuffer(path: string): Promise<ArrayBuffer> {
  const res = await check(await send(path, { headers: authHeaders() }));
  return res.arrayBuffer();
}

export async function download(path: string, filename: string) {
  const url = await blobUrl(path);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const projectFile = (projectId: string, rel: string) =>
  `/api/projects/${projectId}/files?path=${encodeURIComponent(rel)}`;
export const mediaContent = (mediaId: string) => `/api/media/${mediaId}/content`;

export function watchJob(jobId: string, onJob: (j: Job) => void, onClose?: () => void): () => void {
  const es = new EventSource(`${BASE}/api/jobs/${jobId}/events?token=${encodeURIComponent(getToken() ?? "")}`);
  es.addEventListener("job", (e) => onJob(JSON.parse((e as MessageEvent).data)));
  es.onerror = () => {
    es.close();
    onClose?.();
  };
  return () => es.close();
}

/** Probes the backend with a real cross-origin request, so a CORS or network problem is visible before anyone submits a form. */
export async function backendReachable(): Promise<{ ok: boolean; detail: string }> {
  try {
    const res = await fetch(`${BASE}/actuator/health`, { cache: "no-store" });
    return res.ok ? { ok: true, detail: `Backend reachable at ${BASE}` } : { ok: false, detail: `Backend answered HTTP ${res.status} at ${BASE}` };
  } catch {
    return { ok: false, detail: `Cannot reach the backend at ${BASE} from ${window.location.origin} (not running, wrong port, or CORS_ORIGINS does not include this origin)` };
  }
}
