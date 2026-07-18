const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// Double-submit CSRF (F15). Same-origin we read the token from the csrf_token
// cookie; cross-site (frontend on Vercel, API on Hugging Face) the browser
// won't let us read the backend-domain cookie, so we capture the token from the
// X-CSRF-Token response header instead — the backend sets it on every auth
// response and on GET /api/v1/auth/csrf. The cookie still travels with the
// request, so the backend's cookie-vs-header compare holds either way.
let csrfToken: string | null = null;

export class ApiError extends Error {
  errorCode: string;
  requestId: string;
  status: number;

  constructor(status: number, errorCode: string, message: string, requestId: string) {
    super(message);
    this.status = status;
    this.errorCode = errorCode;
    this.requestId = requestId;
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };

  // Double-submit CSRF (F15): the backend issues a non-httponly csrf_token
  // cookie alongside the session cookies; mutating requests must echo it
  // back in this header, or the CSRFMiddleware rejects them with 403.
  if (MUTATING_METHODS.has(method)) {
    const token = csrfToken ?? readCookie("csrf_token");
    if (token) headers["X-CSRF-Token"] = token;
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });

  // The backend echoes the CSRF token here on auth responses and GET /auth/csrf;
  // stash it so cross-site mutating requests can send it back (see above).
  const freshCsrf = res.headers.get("X-CSRF-Token");
  if (freshCsrf) csrfToken = freshCsrf;

  if (res.status === 204) {
    return undefined as T;
  }

  const body = await res.json().catch(() => null);

  if (!res.ok) {
    throw new ApiError(
      res.status,
      body?.error_code ?? "unknown_error",
      body?.message ?? "Something went wrong. Please try again.",
      body?.request_id ?? "",
    );
  }

  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "POST", body: data !== undefined ? JSON.stringify(data) : undefined }),
  patch: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "PATCH", body: data !== undefined ? JSON.stringify(data) : undefined }),
  put: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "PUT", body: data !== undefined ? JSON.stringify(data) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function apiUrl(path: string): string {
  return `${API_URL}${path}`;
}
