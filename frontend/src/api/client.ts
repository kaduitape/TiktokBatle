import { clearToken, getToken } from "../auth";

const configuredApiUrl = (import.meta as any).env?.VITE_API_URL;

// An explicitly empty value is used by the Docker build: nginx proxies API
// and WebSocket traffic on the same public origin.  Preserve localhost as the
// convenient default for `npm run dev`, where that proxy does not exist.
export const API_BASE = configuredApiUrl === ""
  ? window.location.origin
  : configuredApiUrl || "http://localhost:8000";

export const WS_BASE = API_BASE.replace(/^http/, "ws");

/** Uploads are served by the API, not by whatever is hosting the panel. A bare
 * "/uploads/x.png" in an <img> would resolve against the panel's own origin,
 * which only happens to work when a proxy puts both behind one address. */
export function assetUrl(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  if (/^(https?:)?\/\//.test(path) || path.startsWith("data:")) return path;
  return `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleUnauthorized(): void {
  clearToken();
  if (!window.location.hash.startsWith("#/admin/login")) {
    window.location.hash = "#/admin/login";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...options,
  });
  if (res.status === 401) {
    handleUnauthorized();
    throw new Error("401 not authenticated");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    // FastAPI puts the human-readable reason in `detail`; showing the raw JSON
    // envelope instead would bury it in the middle of a status line.
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === "string") detail = parsed.detail;
    } catch {
      /* not JSON -- keep the raw body */
    }
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: async (path: string, file: File): Promise<{ url: string }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: form, headers: authHeaders() });
    if (res.status === 401) {
      handleUnauthorized();
      throw new Error("401 not authenticated");
    }
    if (!res.ok) {
      // Same treatment `request` gives: the server explains why it refused
      // the file ("envie uma imagem"), and a bare status number hides it.
      const text = await res.text().catch(() => "");
      let detail = text;
      try {
        const parsed = JSON.parse(text);
        if (typeof parsed?.detail === "string") detail = parsed.detail;
      } catch {
        /* not JSON -- keep the raw body */
      }
      throw new Error(detail || `${res.status} ${res.statusText}`);
    }
    return res.json();
  },
};
