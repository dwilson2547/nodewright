// Workspaces, organised in the user's folders (design §11.2). Drag a workspace
// or folder onto a folder to file it there, or onto empty space for the top level.
import { useEffect, useState, type DragEvent } from "react";
import type { Folder, Workspace } from "./api";

export type SidebarActions = {
  open: (wsId: string) => void;
  newWorkspace: (folderId: string | null) => void;
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

export function Sidebar({ folders, workspaces, current, act }: {
  folders: Folder[];
  workspaces: Workspace[];
  current: string | null;
  act: SidebarActions;
}) {
  const [open, toggle] = useExpanded();
  const [over, setOver] = useState<string | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  const known = new Set(folders.map((f) => f.id));
  const kids = (parent: string | null) => folders.filter((f) => (f.parent_id ?? null) === parent);
  const filed = (folder: string | null) => workspaces.filter((w) =>
    (w.folder_id && known.has(w.folder_id) ? w.folder_id : null) === folder);

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
      style={{ paddingLeft: 10 + depth * 14 }} onClick={() => act.open(w.id)} title={w.name}
      {...dragging({ kind: "ws", id: w.id })}>
      <span className="sb-name">{w.name}</span>
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
      </div>
    </aside>
  );
}
