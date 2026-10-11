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

// One id per page load: the server's edit lease belongs to a browser tab, so a
// second tab of the same user is "someone else" (api/nodewright/leases.py).
export const CLIENT_ID = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
export const isMine = (lease: Lease | null) => !!lease && lease.holder.startsWith("ui:") && lease.holder.endsWith(":" + CLIENT_ID);

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Nodewright": "1", "X-Nodewright-Client": CLIENT_ID };
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
export type Config = {
  oidc: boolean;
  dev_login: boolean;
  max_canvas_bytes: number;
  version: string;
  attachments: boolean;
  max_attachment_bytes: number;
};
export type Attachment = {
  id: string; name: string; content_type: string; size: number; image: boolean; file: string; url: string;
};
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
export type Lease = {
  holder: string;
  kind: "ui" | "agent";
  label: string;
  expires_at: string;
  seconds_left: number;
  message: string;
};
export type CanvasFull = CanvasMeta & { data: JsonCanvas; lease: Lease | null; can_edit: boolean };
export type CanvasEvent =
  | { type: "hello"; revision: number; lease: Lease | null }
  | { type: "revision"; revision: number; source: string; by: string; client: string }
  | { type: "lease"; lease: Lease | null };
export type Token = { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null };
export type NewToken = Token & { token: string; mcp_url: string };
export type Grant = { id: string; client_name: string; created_at: string; last_used_at: string | null };
export type StyleGuide = { text: string; is_default: boolean };
export type TemplateKind = "stencil" | "fragment" | "page";
export type Template = { id: string; name: string; kind: TemplateKind; builtin: boolean; data: JsonCanvas };
export type Templates = { templates: Template[]; default_page: string };

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
  createCanvas: (wsId: string, name: string, data?: JsonCanvas, template?: string) =>
    call<CanvasMeta>("POST", `/api/workspaces/${wsId}/canvases`, { name, data, template }),
  canvas: (id: string) => call<CanvasFull>("GET", `/api/canvases/${id}`),
  saveCanvas: (id: string, base_revision: number, data: JsonCanvas) =>
    call<{ id: string; revision: number }>("PUT", `/api/canvases/${id}`, { base_revision, data }),
  patchCanvas: (id: string, patch: { name?: string; position?: number }) =>
    call<CanvasMeta>("PATCH", `/api/canvases/${id}`, patch),
  deleteCanvas: (id: string) => call("DELETE", `/api/canvases/${id}`),
  lease: (id: string) => call<{ lease: Lease | null }>("GET", `/api/canvases/${id}/lease`),
  takeLease: (id: string, force = false) =>
    call<{ lease: Lease }>("POST", `/api/canvases/${id}/lease${force ? "?force=true" : ""}`),
  releaseLease: (id: string) => call("DELETE", `/api/canvases/${id}/lease`),
  tokens: () => call<Token[]>("GET", "/api/tokens"),
  createToken: (name: string) => call<NewToken>("POST", "/api/tokens", { name }),
  revokeToken: (id: string) => call("DELETE", `/api/tokens/${id}`),
  grants: () => call<{ grants: Grant[] }>("GET", "/api/oauth/grants").then((r) => r.grants),
  revokeGrant: (id: string) => call("DELETE", `/api/oauth/grants/${id}`),
  styleGuide: () => call<StyleGuide>("GET", "/api/style-guide"),
  saveStyleGuide: (text: string) => call<StyleGuide>("PUT", "/api/style-guide", { text }),
  templates: () => call<Templates>("GET", "/api/templates"),
  createTemplate: (name: string, kind: TemplateKind, data: JsonCanvas) =>
    call<Template>("POST", "/api/templates", { name, kind, data }),
  renameTemplate: (id: string, name: string) => call<Template>("PATCH", `/api/templates/${id}`, { name }),
  deleteTemplate: (id: string) => call("DELETE", `/api/templates/${id}`),
  uploadAttachment: async (wsId: string, file: File): Promise<Attachment> => {
    const r = await fetch(`/api/workspaces/${wsId}/attachments`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-Nodewright": "1",
        "X-Nodewright-Client": CLIENT_ID,
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new ApiError(r.status, data);
    return data as Attachment;
  },
  setDefaultPage: (template: string) =>
    call<{ default_page: string }>("PUT", "/api/templates-default-page", { template }),
};

/** Best-effort lease release while the page is unloading. */
export function releaseOnUnload(id: string) {
  void fetch(`/api/canvases/${id}/lease`, {
    method: "DELETE",
    keepalive: true,
    credentials: "same-origin",
    headers: { "X-Nodewright": "1", "X-Nodewright-Client": CLIENT_ID },
  }).catch(() => undefined);
}
