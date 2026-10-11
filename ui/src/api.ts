// Every write carries X-Nodewright: the server's CSRF guard (api/nodewright/auth.py).

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, body: any) {
    super(typeof body?.detail === "string" ? body.detail : `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Nodewright": "1" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(url, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 204) return undefined as T;
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, data);
  return data as T;
}

export type Me = { id: string; username: string };
export type Config = { oidc: boolean; dev_login: boolean; max_canvas_bytes: number; version: string };
export type Workspace = { id: string; name: string; updated_at: string };
export type CanvasMeta = {
  id: string;
  workspace_id: string;
  name: string;
  position: number;
  revision: number;
  updated_at: string;
};
export type JsonCanvas = { nodes?: any[]; edges?: any[]; [k: string]: unknown };
export type CanvasFull = CanvasMeta & { data: JsonCanvas };

export const api = {
  config: () => call<Config>("GET", "/api/config"),
  me: () => call<Me>("GET", "/api/me"),
  logout: () => call("POST", "/api/auth/logout"),
  devLogin: (name: string) => call<Me>("POST", "/api/auth/dev-login", { name }),
  workspaces: () => call<Workspace[]>("GET", "/api/workspaces"),
  createWorkspace: (name: string) => call<Workspace>("POST", "/api/workspaces", { name }),
  renameWorkspace: (id: string, name: string) => call<Workspace>("PATCH", `/api/workspaces/${id}`, { name }),
  deleteWorkspace: (id: string) => call("DELETE", `/api/workspaces/${id}`),
  canvases: (wsId: string) => call<CanvasMeta[]>("GET", `/api/workspaces/${wsId}/canvases`),
  createCanvas: (wsId: string, name: string, data?: JsonCanvas) =>
    call<CanvasMeta>("POST", `/api/workspaces/${wsId}/canvases`, { name, data }),
  canvas: (id: string) => call<CanvasFull>("GET", `/api/canvases/${id}`),
  saveCanvas: (id: string, base_revision: number, data: JsonCanvas) =>
    call<{ id: string; revision: number }>("PUT", `/api/canvases/${id}`, { base_revision, data }),
  patchCanvas: (id: string, patch: { name?: string; position?: number }) =>
    call<CanvasMeta>("PATCH", `/api/canvases/${id}`, patch),
  deleteCanvas: (id: string) => call("DELETE", `/api/canvases/${id}`),
};
