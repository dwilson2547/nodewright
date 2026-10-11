import { useCallback, useEffect, useRef, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { api, ApiError, type CanvasMeta, type Config, type Me, type Workspace } from "./api";
import { Editor, type EditorHandle, type SaveStatus } from "./Editor";
import { AgentSettings } from "./Settings";

const STATUS_TEXT: Record<SaveStatus, string> = {
  loading: "Loading…",
  saved: "Saved",
  unsaved: "Unsaved",
  saving: "Saving…",
  conflict: "Conflict",
  locked: "Locked",
  error: "Save failed",
};

// /?canvas=<id> opens that tab (agents hand these links out).
function linkedCanvas(): string | null {
  const id = new URLSearchParams(location.search).get("canvas");
  if (id) history.replaceState(null, "", "/");
  return id;
}

function signinError(): string | null {
  const e = new URLSearchParams(location.search).get("signin_error");
  if (e) history.replaceState(null, "", "/");
  return e ? "Sign-in didn't complete. Try again." : null;
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = (name.replace(/[^\w .-]/g, "").trim() || "canvas") + ".canvas";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function SignIn({ config, onDone }: { config: Config; onDone: () => void }) {
  const [error] = useState(signinError);
  const [name, setName] = useState("dev");
  return (
    <div className="signin">
      <h1>nodewright</h1>
      <p className="muted">Diagrams on JSON Canvas.</p>
      {error && <p className="error">{error}</p>}
      {config.oidc && <a className="button primary" href="/api/auth/oidc/login">Sign in</a>}
      {config.dev_login && (
        <form onSubmit={(e) => { e.preventDefault(); void api.devLogin(name).then(onDone); }}>
          <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Dev user" />
          <button type="submit">Dev sign-in</button>
        </form>
      )}
      {!config.oidc && !config.dev_login && <p className="error">Sign-in isn't configured on this server.</p>}
    </div>
  );
}

function Tab({ tab, active, onOpen, onRename, onDelete }: {
  tab: CanvasMeta;
  active: boolean;
  onOpen: () => void;
  onRename: (name: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(tab.name);
  const commit = () => {
    setEditing(false);
    const v = draft.trim();
    if (v && v !== tab.name) onRename(v);
  };
  return (
    <div className={"tab" + (active ? " active" : "")} onClick={onOpen}
      onDoubleClick={() => { setDraft(tab.name); setEditing(true); }} title="Double-click to rename">
      {editing ? (
        <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }} />
      ) : (
        <span>{tab.name}</span>
      )}
      <button className="tab-x" title="Delete tab" onClick={(e) => { e.stopPropagation(); onDelete(); }}>×</button>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [wsId, setWsId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<CanvasMeta[]>([]);
  const [tabId, setTabId] = useState<string | null>(null);
  const [status, setStatus] = useState<SaveStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const linked = useRef<string | null>(linkedCanvas());
  const editor = useRef<EditorHandle>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  const loadMe = useCallback(() => {
    api.me().then(setMe, (e) => (e instanceof ApiError && e.status === 401 ? setMe(null) : fail(e)));
  }, []);

  useEffect(() => {
    api.config().then(setConfig, fail);
    loadMe();
  }, [loadMe]);

  const loadWorkspaces = useCallback(async (prefer?: string) => {
    const list = await api.workspaces();
    setWorkspaces(list);
    if (!prefer && linked.current) {
      const c = await api.canvas(linked.current).catch(() => null);
      if (c) {
        localStorage.setItem("nw.tab." + c.workspace_id, c.id);
        prefer = c.workspace_id;
      }
      linked.current = null;
    }
    const saved = prefer ?? localStorage.getItem("nw.ws");
    setWsId(list.find((w) => w.id === saved)?.id ?? list[0]?.id ?? null);
  }, []);

  useEffect(() => {
    if (me) loadWorkspaces().catch(fail);
  }, [me, loadWorkspaces]);

  const loadTabs = useCallback(async (id: string, prefer?: string) => {
    let list = await api.canvases(id);
    if (list.length === 0) {
      await api.createCanvas(id, "Untitled");
      list = await api.canvases(id);
    }
    setTabs(list);
    const saved = prefer ?? localStorage.getItem("nw.tab." + id);
    setTabId(list.find((t) => t.id === saved)?.id ?? list[0].id);
  }, []);

  useEffect(() => {
    if (!wsId) return;
    localStorage.setItem("nw.ws", wsId);
    loadTabs(wsId).catch(fail);
  }, [wsId, loadTabs]);

  useEffect(() => {
    if (wsId && tabId) localStorage.setItem("nw.tab." + wsId, tabId);
  }, [wsId, tabId]);

  // Leaving a tab or workspace saves it first.
  const leave = async () => (editor.current ? editor.current.flush() : true);

  const openTab = async (id: string) => {
    if (id === tabId) return;
    await leave();
    setTabId(id);
  };

  const switchWorkspace = async (id: string) => {
    await leave();
    setTabId(null);
    setWsId(id);
  };

  const newTab = async () => {
    if (!wsId) return;
    await leave();
    const t = await api.createCanvas(wsId, `Untitled ${tabs.length + 1}`).catch(fail);
    if (t) await loadTabs(wsId, t.id);
  };

  const renameTab = async (t: CanvasMeta, name: string) => {
    await api.patchCanvas(t.id, { name }).catch(fail);
    setTabs((ts) => ts.map((x) => (x.id === t.id ? { ...x, name } : x)));
  };

  const deleteTab = async (t: CanvasMeta) => {
    if (!wsId || !confirm(`Delete "${t.name}"? This can't be undone.`)) return;
    await api.deleteCanvas(t.id).catch(fail);
    await loadTabs(wsId, t.id === tabId ? undefined : tabId ?? undefined);
  };

  const importFile = async (file: File) => {
    if (!wsId) return;
    try {
      const data = JSON.parse(await file.text());
      await leave();
      const t = await api.createCanvas(wsId, file.name.replace(/\.canvas$/i, "") || "Imported", data);
      await loadTabs(wsId, t.id);
    } catch (e) {
      fail(e instanceof SyntaxError ? new Error("That file isn't JSON.") : e);
    }
  };

  const exportTab = () => {
    const doc = editor.current?.exportDoc();
    const t = tabs.find((x) => x.id === tabId);
    if (doc && t) download(t.name, JSON.stringify(doc, null, "\t"));
  };

  const newWorkspace = async () => {
    const name = prompt("Name for the new workspace", "New workspace")?.trim();
    if (!name) return;
    await leave();
    const w = await api.createWorkspace(name).catch(fail);
    if (w) {
      setTabId(null);
      await loadWorkspaces(w.id);
    }
  };

  const renameWorkspace = async () => {
    const ws = workspaces.find((w) => w.id === wsId);
    const name = ws && prompt("Rename workspace", ws.name)?.trim();
    if (!ws || !name) return;
    await api.renameWorkspace(ws.id, name).catch(fail);
    await loadWorkspaces(ws.id);
  };

  const deleteWorkspace = async () => {
    const ws = workspaces.find((w) => w.id === wsId);
    if (!ws || !confirm(`Delete workspace "${ws.name}" and all its tabs? This can't be undone.`)) return;
    await api.deleteWorkspace(ws.id).catch(fail);
    const rest = workspaces.filter((w) => w.id !== ws.id);
    if (rest.length === 0) await api.createWorkspace("My workspace");
    setTabId(null);
    await loadWorkspaces(rest[0]?.id);
  };

  const signOut = async () => {
    await leave();
    await api.logout().catch(() => undefined);
    setMe(null);
  };

  if (!config || me === undefined) return <div className="center-msg">{error ?? "Loading…"}</div>;
  if (me === null) return <SignIn config={config} onDone={loadMe} />;

  return (
    <div className="app">
      <header>
        <strong className="brand">nodewright</strong>
        <select value={wsId ?? ""} aria-label="Workspace" onChange={(e) => {
          if (e.target.value === "__new") void newWorkspace();
          else void switchWorkspace(e.target.value);
        }}>
          {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          <option value="__new">+ New workspace…</option>
        </select>
        <button onClick={renameWorkspace} title="Rename workspace">Rename</button>
        <button onClick={deleteWorkspace} title="Delete workspace">Delete</button>
        <span className="grow" />
        <span className={"status s-" + status}>{STATUS_TEXT[status]}</span>
        <button onClick={() => fileInput.current?.click()} title="Open a .canvas file as a new tab">Import</button>
        <button onClick={exportTab} title="Download this tab as a .canvas file">Export</button>
        <input ref={fileInput} type="file" accept=".canvas,application/json" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void importFile(f);
        }} />
        <button onClick={() => setSettingsOpen(true)} title="Access tokens and style guide for AI agents (MCP)">Agents</button>
        <span className="muted">{me.username}</span>
        <button onClick={signOut}>Sign out</button>
      </header>
      <nav className="tabs">
        {tabs.map((t) => (
          <Tab key={t.id} tab={t} active={t.id === tabId} onOpen={() => void openTab(t.id)}
            onRename={(n) => void renameTab(t, n)} onDelete={() => void deleteTab(t)} />
        ))}
        <button className="tab-add" onClick={newTab} title="New tab">+</button>
      </nav>
      {error && (
        <div className="error-bar">
          {error} <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}
      <main>
        {tabId && (
          <ReactFlowProvider key={tabId}>
            <Editor ref={editor} canvasId={tabId} onStatus={setStatus} />
          </ReactFlowProvider>
        )}
      </main>
      {settingsOpen && <AgentSettings onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
