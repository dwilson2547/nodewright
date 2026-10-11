import { useCallback, useEffect, useRef, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { api, ApiError, type CanvasMeta, type Config, type Folder, type Me, type Workspace } from "./api";
import { Editor, type EditorHandle, type SaveStatus } from "./Editor";
import { AgentSettings } from "./Settings";
import { ShareDialog } from "./ShareDialog";
import { Sidebar } from "./Sidebar";
import { TabLinksContext } from "./tablinks";

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
  onRename?: (name: string) => void;
  onDelete?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(tab.name);
  const commit = () => {
    setEditing(false);
    const v = draft.trim();
    if (v && v !== tab.name) onRename?.(v);
  };
  return (
    <div className={"tab" + (active ? " active" : "")} onClick={onOpen}
      onDoubleClick={() => { if (onRename) { setDraft(tab.name); setEditing(true); } }}
      title={onRename ? "Double-click to rename" : undefined}>
      {editing ? (
        <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }} />
      ) : (
        <span>{tab.name}</span>
      )}
      {onDelete && (
        <button className="tab-x" title="Delete tab" onClick={(e) => { e.stopPropagation(); onDelete(); }}>×</button>
      )}
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [sidebar, setSidebar] = useState(() => localStorage.getItem("nw.sidebar") !== "0");
  const [wsId, setWsId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<CanvasMeta[]>([]);
  const [tabId, setTabId] = useState<string | null>(null);
  const [status, setStatus] = useState<SaveStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [focus, setFocus] = useState<{ canvas: string; node: string } | null>(null);
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
    const [list, fs] = await Promise.all([api.workspaces(), api.folders()]);
    setWorkspaces(list);
    setFolders(fs);
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

  // A tab link: open the tab (saving this one first) and focus its #node.
  const followLink = async (id: string, node?: string) => {
    if (id === tabId) {
      if (node) editor.current?.focusNode(node);
      return;
    }
    setFocus(node ? { canvas: id, node } : null);
    await openTab(id);
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
    setExportOpen(false);
    const doc = editor.current?.exportDoc();
    const t = tabs.find((x) => x.id === tabId);
    if (doc && t) download(t.name, JSON.stringify(doc, null, "\t"));
  };

  // Save pending edits first, so the zip (built from the server's copy) has them.
  const exportWorkspace = async () => {
    setExportOpen(false);
    if (!wsId) return;
    await editor.current?.flush();
    const a = document.createElement("a");
    a.href = `/api/workspaces/${wsId}/export`;
    a.click();
  };

  const newWorkspace = async (folderId: string | null = null) => {
    const name = prompt("Name for the new workspace", "New workspace")?.trim();
    if (!name) return;
    await leave();
    const w = await api.createWorkspace(name).catch(fail);
    if (w) {
      if (folderId) await api.fileWorkspace(w.id, folderId).catch(fail);
      setTabId(null);
      await loadWorkspaces(w.id);
    }
  };

  const refreshTree = () => loadWorkspaces(wsId ?? undefined).catch(fail);

  const newFolder = async (parentId: string | null) => {
    const name = prompt("Folder name", "New folder")?.trim();
    if (!name) return;
    await api.createFolder(name, parentId).catch(fail);
    await refreshTree();
  };

  const renameFolder = async (f: Folder) => {
    const name = prompt("Rename folder", f.name)?.trim();
    if (!name || name === f.name) return;
    await api.patchFolder(f.id, { name }).catch(fail);
    await refreshTree();
  };

  const deleteFolder = async (f: Folder) => {
    if (!confirm(`Delete folder "${f.name}" and its subfolders? Workspaces in them move to the top level; none are deleted.`)) return;
    await api.deleteFolder(f.id).catch(fail);
    await refreshTree();
  };

  const fileWorkspace = async (id: string, folderId: string | null) => {
    setWorkspaces((ws) => ws.map((w) => (w.id === id ? { ...w, folder_id: folderId } : w)));
    await api.fileWorkspace(id, folderId).catch(fail);
    await refreshTree();
  };

  const moveFolder = async (id: string, parentId: string | null) => {
    await api.patchFolder(id, { parent_id: parentId }).catch(fail);
    await refreshTree();
  };

  const toggleSidebar = () => setSidebar((v) => {
    localStorage.setItem("nw.sidebar", v ? "0" : "1");
    return !v;
  });

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

  // After leaving a shared workspace (ShareDialog): move to another, as for a delete.
  const leftWorkspace = async () => {
    setShareOpen(false);
    const rest = workspaces.filter((w) => w.id !== wsId);
    if (rest.length === 0) await api.createWorkspace("My workspace").catch(fail);
    await leave();
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
  const ws = workspaces.find((w) => w.id === wsId);
  const owner = ws?.role === "owner";
  const editable = owner || ws?.role === "editor";

  return (
    <div className="app">
      <header>
        <button className="sb-toggle" onClick={toggleSidebar} title={sidebar ? "Hide workspaces" : "Show workspaces"}
          aria-label="Toggle workspaces">☰</button>
        <strong className="brand">nodewright</strong>
        <span className="ws-name">{ws?.name}</span>
        {ws && !owner && <span className="muted" title={`Shared with you by ${ws.owner}`}>{ws.role} · {ws.owner}</span>}
        {owner && <button onClick={renameWorkspace} title="Rename workspace">Rename</button>}
        {owner && <button onClick={deleteWorkspace} title="Delete workspace">Delete</button>}
        <span className="grow" />
        <span className={"status s-" + status}>{STATUS_TEXT[status]}</span>
        {editable && <button onClick={() => fileInput.current?.click()} title="Open a .canvas file as a new tab">Import</button>}
        <span className="menu-anchor" onMouseLeave={() => setExportOpen(false)}>
          <button onClick={() => setExportOpen((v) => !v)} aria-expanded={exportOpen}>Export ▾</button>
          {exportOpen && (
            <div className="sb-menu" role="menu">
              <button role="menuitem" onClick={exportTab} disabled={!tabId}>This tab (.canvas)</button>
              <button role="menuitem" onClick={() => void exportWorkspace()}
                title="Every tab and the files they show; unzipped, it opens as an Obsidian vault">
                Whole workspace (.zip)
              </button>
            </div>
          )}
        </span>
        <input ref={fileInput} type="file" accept=".canvas,application/json" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void importFile(f);
        }} />
        <button onClick={() => setShareOpen(true)} disabled={!ws}
          title={owner ? "Members and read-only links" : "Who has access"}>Share</button>
        <button onClick={() => setSettingsOpen(true)} title="Access tokens and style guide for AI agents (MCP)">Agents</button>
        <span className="muted">{me.username}</span>
        <button onClick={signOut}>Sign out</button>
      </header>
      <div className="body">
      {sidebar && (
        <Sidebar folders={folders} workspaces={workspaces} current={wsId} act={{
          open: (id) => { if (id !== wsId) void switchWorkspace(id); },
          newWorkspace: (f) => void newWorkspace(f),
          newFolder: (p) => void newFolder(p),
          renameFolder: (f) => void renameFolder(f),
          deleteFolder: (f) => void deleteFolder(f),
          fileWorkspace: (w, f) => void fileWorkspace(w, f),
          moveFolder: (f, p) => void moveFolder(f, p),
        }} />
      )}
      <div className="work">
      <nav className="tabs">
        {tabs.map((t) => (
          <Tab key={t.id} tab={t} active={t.id === tabId} onOpen={() => void openTab(t.id)}
            onRename={editable ? (n) => void renameTab(t, n) : undefined}
            onDelete={editable ? () => void deleteTab(t) : undefined} />
        ))}
        {editable && <button className="tab-add" onClick={newTab} title="New tab">+</button>}
      </nav>
      {error && (
        <div className="error-bar">
          {error} <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}
      <main>
        {tabId && (
          <TabLinksContext.Provider value={{ tabs, current: tabId, open: (id, node) => void followLink(id, node) }}>
            <ReactFlowProvider key={tabId}>
              <Editor ref={editor} canvasId={tabId} onStatus={setStatus}
                focusNode={focus?.canvas === tabId ? focus.node : undefined}
                attachmentLimit={config.attachments ? config.max_attachment_bytes : undefined} />
            </ReactFlowProvider>
          </TabLinksContext.Provider>
        )}
      </main>
      </div>
      </div>
      {settingsOpen && <AgentSettings onClose={() => setSettingsOpen(false)} />}
      {shareOpen && ws && (
        <ShareDialog workspace={ws} canvasId={tabId} canvasName={tabs.find((t) => t.id === tabId)?.name ?? ""}
          me={me.username} onClose={() => setShareOpen(false)} onLeft={() => void leftWorkspace()} />
      )}
    </div>
  );
}
