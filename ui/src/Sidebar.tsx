// Workspaces, organised in the user's folders (design §11.2). Drag a workspace
// or folder onto a folder to file it there, or onto empty space for the top level.
// Below the folders, a heading per organisation (design §19) lists its
// workspaces that aren't in one of your folders; filing never moves a
// workspace between orgs (that's Share → Move).
import { useEffect, useState, type DragEvent } from "react";
import type { Folder, Org, Workspace } from "./api";

export type SidebarActions = {
  open: (wsId: string) => void;
  newWorkspace: (folderId: string | null, orgId?: string) => void;
  newFolder: (parentId: string | null) => void;
  renameFolder: (f: Folder) => void;
  deleteFolder: (f: Folder) => void;
  fileWorkspace: (wsId: string, folderId: string | null) => void;
  moveFolder: (folderId: string, parentId: string | null) => void;
};

type Drag = { kind: "ws" | "folder"; id: string };
const MIME = "application/x-nodewright";

function readDrag(e: DragEvent): Drag | null {
  try {
    return JSON.parse(e.dataTransfer.getData(MIME)) as Drag;
  } catch {
    return null;
  }
}

function useExpanded() {
  const [open, setOpen] = useState<Set<string>>(() =>
    new Set(JSON.parse(localStorage.getItem("nw.folders.open") ?? "[]") as string[]));
  useEffect(() => localStorage.setItem("nw.folders.open", JSON.stringify([...open])), [open]);
  const toggle = (id: string, to?: boolean) => setOpen((s) => {
    const n = new Set(s);
    if (to ?? !n.has(id)) n.add(id); else n.delete(id);
    return n;
  });
  return [open, toggle] as const;
}

export function Sidebar({ folders, workspaces, orgs, current, act }: {
  folders: Folder[];
  workspaces: Workspace[];
  /** Orgs you're in; orgs you only reach as a guest show up from their workspaces. */
  orgs: Org[];
  current: string | null;
  act: SidebarActions;
}) {
  const [open, toggle] = useExpanded();
  const [over, setOver] = useState<string | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  const known = new Set(folders.map((f) => f.id));
  const kids = (parent: string | null) => folders.filter((f) => (f.parent_id ?? null) === parent);
  const folderOf = (w: Workspace) => (w.folder_id && known.has(w.folder_id) ? w.folder_id : null);
  // Unfiled org workspaces go under their org's heading, not the top level.
  const filed = (folder: string | null) => workspaces.filter((w) =>
    folderOf(w) === folder && (folder !== null || !w.org));
  const orgList = orgs.map((o) => ({ id: o.id, name: o.name, mine: true }));
  for (const w of workspaces) {
    if (w.org && !orgList.some((o) => o.id === w.org!.id)) orgList.push({ id: w.org.id, name: w.org.name, mine: false });
  }

  // Open the folders on the way to the current workspace.
  useEffect(() => {
    let f = workspaces.find((w) => w.id === current)?.folder_id;
    while (f) {
      const id: string = f;
      if (!open.has(id)) toggle(id, true);
      f = folders.find((x) => x.id === id)?.parent_id ?? null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, folders, workspaces]);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menu]);

  const drop = (target: string | null) => (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setOver(null);
    const d = readDrag(e);
    if (!d) return;
    if (d.kind === "ws") act.fileWorkspace(d.id, target);
    else if (d.id !== target) act.moveFolder(d.id, target);
  };
  const dropZone = (target: string | null) => ({
    onDragOver: (e: DragEvent) => {
      if (!e.dataTransfer.types.includes(MIME)) return;
      e.preventDefault();
      e.stopPropagation();
      setOver(target ?? "");
    },
    onDragLeave: () => setOver(null),
    onDrop: drop(target),
  });
  const dragging = (d: Drag) => ({
    draggable: true,
    onDragStart: (e: DragEvent) => {
      e.stopPropagation();
      e.dataTransfer.setData(MIME, JSON.stringify(d));
      e.dataTransfer.effectAllowed = "move";
    },
  });

  const wsRow = (w: Workspace, depth: number) => (
    <div key={w.id} className={"sb-row sb-ws" + (w.id === current ? " active" : "")}
      style={{ paddingLeft: 10 + depth * 14 }} onClick={() => act.open(w.id)}
      title={w.org ? `${w.name} — ${w.org.name} (${w.role})`
        : w.role === "owner" ? w.name : `${w.name} — shared by ${w.owner} (${w.role})`}
      {...dragging({ kind: "ws", id: w.id })}>
      <span className="sb-name">{w.name}</span>
      {w.org && folderOf(w) && <span className="sb-org">{w.org.name}</span>}
      {!w.org && w.role !== "owner" && <span className="sb-shared" aria-label="shared with you">⇄</span>}
    </div>
  );

  const folderTree = (f: Folder, depth: number) => {
    const isOpen = open.has(f.id);
    return (
      <div key={f.id}>
        <div className={"sb-row sb-folder" + (over === f.id ? " over" : "")}
          style={{ paddingLeft: 4 + depth * 14 }} onClick={() => toggle(f.id)} title={f.name}
          {...dragging({ kind: "folder", id: f.id })} {...dropZone(f.id)}>
          <span className="sb-caret">{isOpen ? "▾" : "▸"}</span>
          <span className="sb-name">{f.name}</span>
          <button className="sb-btn" title="New workspace in this folder"
            onClick={(e) => { e.stopPropagation(); toggle(f.id, true); act.newWorkspace(f.id); }}>+</button>
          <button className="sb-btn" title="Folder actions"
            onClick={(e) => { e.stopPropagation(); setMenu(menu === f.id ? null : f.id); }}>⋯</button>
          {menu === f.id && (
            <div className="sb-menu" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => { setMenu(null); toggle(f.id, true); act.newFolder(f.id); }}>New subfolder</button>
              <button onClick={() => { setMenu(null); act.renameFolder(f); }}>Rename</button>
              <button onClick={() => { setMenu(null); act.deleteFolder(f); }}>Delete folder</button>
            </div>
          )}
        </div>
        {isOpen && (
          <>
            {kids(f.id).map((k) => folderTree(k, depth + 1))}
            {filed(f.id).map((w) => wsRow(w, depth + 1))}
            {!kids(f.id).length && !filed(f.id).length && (
              <div className="sb-row muted sb-empty" style={{ paddingLeft: 24 + depth * 14 }}>Empty</div>
            )}
          </>
        )}
      </div>
    );
  };

  return (
    <aside className={"sidebar" + (over === "" ? " over" : "")} {...dropZone(null)}>
      <div className="sb-head">
        <span>Workspaces</span>
        <span className="grow" />
        <button className="sb-btn" title="New folder" onClick={() => act.newFolder(null)}>+ Folder</button>
        <button className="sb-btn" title="New workspace" onClick={() => act.newWorkspace(null)}>+ New</button>
      </div>
      <div className="sb-list">
        {kids(null).map((f) => folderTree(f, 0))}
        {filed(null).map((w) => wsRow(w, 0))}
        {orgList.map((o) => {
          const rows = workspaces.filter((w) => w.org?.id === o.id && folderOf(w) === null);
          const isOpen = !open.has("org-closed:" + o.id);
          return (
            <div key={o.id} className="sb-orgsec">
              <div className="sb-row sb-orghead" onClick={() => toggle("org-closed:" + o.id)}
                title={o.mine ? o.name : `${o.name}: you have access to some of its workspaces`} {...dropZone(null)}>
                <span className="sb-caret">{isOpen ? "▾" : "▸"}</span>
                <span className="sb-name">{o.name}</span>
                {o.mine && (
                  <button className="sb-btn" title={`New workspace in ${o.name}`}
                    onClick={(e) => { e.stopPropagation(); act.newWorkspace(null, o.id); }}>+</button>
                )}
              </div>
              {isOpen && rows.map((w) => wsRow(w, 1))}
              {isOpen && !rows.length && (
                <div className="sb-row muted sb-empty" style={{ paddingLeft: 24 }}>None outside your folders</div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
