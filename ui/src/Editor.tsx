import {
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  reconnectEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import { api, ApiError, CLIENT_ID, isMine, releaseOnUnload, type CanvasEvent, type Icon, type JsonCanvas, type SchemaParse, type Lease, type Template } from "./api";
import { ICON_DRAG_TYPE } from "./icons";
import { DRAG_TYPE, Palette } from "./Palette";
import { endFields, flipped, orient, orientationOf, portsOf, turned, type Orientation, type Port } from "./ports";
import { PortsPanel } from "./PortsPanel";
import { HistoryPanel, when } from "./HistoryPanel";
import { ReadOnlyFlow } from "./ReadOnlyFlow";
import { isWireEdge } from "./wires";
import {
  PRESETS,
  edgeEnds,
  edgeVisual,
  newId,
  toCanvas,
  toFlow,
  type CEdge,
  type CNode,
} from "./canvasMapping";
import { isSymbol, netName, nodeTypes, ReadOnly, SchemaOps, SelectedNet } from "./nodes";
import { formatForFile, SAMPLES, SCHEMA_FORMATS, type SchemaFormat } from "./schema";
import { RoutedEdge } from "./edges";
import { Markers } from "./markers";
import { canvasFile, TabLinksContext } from "./tablinks";
import {
  CORNER_RADII, EDGE_ARROWS, ICON_COLORS, EDGE_PATHS, EDGE_ROUTES, LINE_WIDTHS, NODE_BORDERS, NODE_SHAPES, TEXT_ALIGN,
  attr, withAttr, type Option,
} from "./styles";

const edgeTypes = { routed: RoutedEdge };
const NET_PORT: Port = { id: "net", side: "left", at: 0.5 };

function Pick({ title, options, value, onChange }: {
  title: string; options: Option[]; value: string; onChange: (v: string) => void;
}) {
  return (
    <select title={title} aria-label={title} value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

/** The value all of `raws` share for a style attribute, or "" if they differ. */
function common(raws: Record<string, any>[], key: string): string {
  const vals = new Set(raws.map((r) => attr(r, key)));
  return vals.size === 1 ? Array.from(vals)[0] : "";
}

export type SaveStatus = "loading" | "saved" | "unsaved" | "saving" | "conflict" | "locked" | "error";
export type EditorHandle = {
  flush: () => Promise<boolean>;
  exportDoc: () => JsonCanvas | null;
  focusNode: (id: string) => void;
};

const SAVE_DEBOUNCE_MS = 700;
const RETRY_MS = 5000;
const HISTORY_LIMIT = 200;
const NOTICE_MS = 4000;
const SIZES: Record<string, [number, number]> = {
  text: [260, 80],
  group: [480, 320],
  link: [320, 70],
  file: [260, 70],
};

type SnapPrefs = { on: boolean; size: number };
function loadSnap(): SnapPrefs {
  try {
    const v = JSON.parse(localStorage.getItem("nw.snap") || "");
    if (typeof v?.on === "boolean" && [10, 20, 40].includes(v.size)) return v;
  } catch {
    /* default below */
  }
  return { on: true, size: 20 };
}

function splitDoc(doc: JsonCanvas) {
  const { nodes: _n, edges: _e, ...extra } = doc;
  return extra;
}

/** What restoring `old` over `now` would do, by element id. */
function diff(old: JsonCanvas, now: JsonCanvas) {
  const count = (a: { id: string }[] = [], b: { id: string }[] = []) => {
    const was = new Map(b.map((x) => [x.id, JSON.stringify(x)]));
    const ids = new Set(a.map((x) => x.id));
    const added = a.filter((x) => !was.has(x.id)).map((x) => x.id);
    const changed = a.filter((x) => was.has(x.id) && was.get(x.id) !== JSON.stringify(x)).map((x) => x.id);
    return { added, changed, removed: b.filter((x) => !ids.has(x.id)).length };
  };
  return { nodes: count(old.nodes, now.nodes), edges: count(old.edges, now.edges) };
}

function summary(d: ReturnType<typeof diff>): string {
  const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;
  const parts: string[] = [];
  const say = (verb: string, nodes: number, edges: number) => {
    const what = [nodes && n(nodes, "node", "nodes"), edges && n(edges, "line", "lines")].filter(Boolean);
    if (what.length) parts.push(`${verb} ${what.join(" and ")}`);
  };
  say("bring back", d.nodes.added.length, d.edges.added.length);
  say("remove", d.nodes.removed, d.edges.removed);
  say("change", d.nodes.changed.length, d.edges.changed.length);
  return parts.length ? `Restoring would ${parts.join(", ")}.` : "Same as the current version.";
}

type Preview = { rev: number; at: string; by: string | null; label: string | null; data: JsonCanvas;
  nodes: CNode[]; edges: CEdge[]; summary: string };

type Props = {
  canvasId: string;
  onStatus: (s: SaveStatus) => void;
  /** The History panel (HistoryPanel.tsx) is open. */
  historyOpen?: boolean;
  onCloseHistory?: () => void;
  focusNode?: string;
  /** Upload limit in bytes when the server stores attachments, else undefined. */
  attachmentLimit?: number;
};

export const Editor = forwardRef<EditorHandle, Props>(function Editor({ canvasId, onStatus, focusNode, attachmentLimit, historyOpen, onCloseHistory }, ref) {
  const [nodes, setNodes, onNodesChange] = useNodesState<CNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CEdge>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatusState] = useState<SaveStatus>("loading");
  const [conflict, setConflict] = useState<{ revision: number; data: JsonCanvas } | null>(null);
  const [snap, setSnap] = useState<SnapPrefs>(loadSnap);
  const [labelEdit, setLabelEdit] = useState<{ id: string; x: number; y: number; value: string } | null>(null);
  const [lease, setLease] = useState<Lease | null>(null);
  const [canEdit, setCanEdit] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(() => localStorage.getItem("nw.palette") !== "0");
  const [tplReload, setTplReload] = useState(0);
  const [portsOpen, setPortsOpen] = useState(false);
  const [head, setHead] = useState(0);
  const [previewed, setPreview] = useState<Preview | null>(null);
  const preview = historyOpen ? previewed : null; // closing the panel ends the preview
  const otherLease = lease && !isMine(lease) ? lease : null;
  const writable = canEdit && !otherLease;
  // While previewing an old version the editor underneath takes no input.
  const readOnly = !writable || !!preview;
  const flow = useReactFlow<CNode, CEdge>();
  const tabLinks = useContext(TabLinksContext);
  const wrapper = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const workspaceId = useRef<string | null>(null);
  const [dropping, setDropping] = useState(false);

  const extra = useRef<Record<string, unknown>>({});
  const revision = useRef(0);
  const lastSaved = useRef("");
  const current = useRef("");
  const undo = useRef<string[]>([]);
  const redo = useRef<string[]>([]);
  const saving = useRef<Promise<boolean> | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const retry = useRef<number | undefined>(undefined);
  const inConflict = useRef(false);
  const restoredFrom = useRef<number | undefined>(undefined);
  const blocked = useRef(false);
  const noticeTimer = useRef<number | undefined>(undefined);
  const groupDrag = useRef<{ id: string; start: { x: number; y: number }; members: Map<string, { x: number; y: number }> } | null>(null);

  const setStatus = useCallback((s: SaveStatus) => {
    setStatusState(s);
    onStatus(s);
  }, [onStatus]);

  const serialize = useCallback(
    (ns = flow.getNodes(), es = flow.getEdges()) => JSON.stringify(toCanvas(ns, es, extra.current)),
    [flow],
  );

  const apply = useCallback((doc: JsonCanvas) => {
    extra.current = splitDoc(doc);
    const f = toFlow(doc);
    setNodes(f.nodes);
    setEdges(f.edges);
    return JSON.stringify(toCanvas(f.nodes, f.edges, extra.current));
  }, [setNodes, setEdges]);

  // Centre a node (a tab link's #subpath) and select it; false if it's gone.
  const showNode = useCallback((id: string) => {
    const n = flow.getNode(id);
    if (!n) return false;
    setNodes((ns) => ns.map((x) => (x.selected !== (x.id === id) ? { ...x, selected: x.id === id } : x)));
    flow.fitView({ nodes: [{ id }], padding: 0.5, maxZoom: 1, duration: 300 });
    return true;
  }, [flow, setNodes]);
  const initialFocus = useRef(focusNode);

  // --- load -----------------------------------------------------------------
  useEffect(() => {
    let alive = true;
    setLoaded(false);
    setStatus("loading");
    api.canvas(canvasId).then(
      (c) => {
        if (!alive) return;
        revision.current = c.revision;
        setHead(c.revision);
        workspaceId.current = c.workspace_id;
        setLease(c.lease);
        setCanEdit(c.can_edit);
        const s = apply(c.data);
        lastSaved.current = current.current = s;
        undo.current = [];
        redo.current = [];
        setLoaded(true);
        setStatus("saved");
        requestAnimationFrame(() => {
          const want = initialFocus.current;
          initialFocus.current = undefined;
          if (!want || !showNode(want)) flow.fitView({ padding: 0.2, maxZoom: 1 });
        });
      },
      (e) => alive && setLoadError(String(e.message || e)),
    );
    return () => {
      alive = false;
    };
  }, [canvasId, apply, flow, setStatus, showNode]);

  // --- saving -----------------------------------------------------------------
  const save = useCallback(async (): Promise<boolean> => {
    if (inConflict.current) return false;
    if (blocked.current) {
      if (serialize() !== lastSaved.current) setStatus("locked");
      return false;
    }
    if (saving.current) {
      await saving.current;
    }
    const body = serialize();
    if (body === lastSaved.current) {
      setStatus("saved");
      return true;
    }
    setStatus("saving");
    const run = (async () => {
      try {
        const r = await api.saveCanvas(canvasId, revision.current, JSON.parse(body), restoredFrom.current);
        restoredFrom.current = undefined;
        revision.current = r.revision;
        setHead(r.revision);
        lastSaved.current = body;
        setStatus(serialize() === body ? "saved" : "unsaved");
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          inConflict.current = true;
          setConflict({ revision: e.body.current.revision, data: e.body.current.data });
          setStatus("conflict");
        } else if (e instanceof ApiError && e.status === 423) {
          blocked.current = true;
          setLease(e.body.lease);
          setStatus("locked");
        } else {
          setStatus("error");
          window.clearTimeout(retry.current);
          retry.current = window.setTimeout(() => void saveRef.current(), RETRY_MS);
        }
        return false;
      } finally {
        saving.current = null;
      }
    })();
    saving.current = run;
    return run;
  }, [canvasId, serialize, setStatus]);

  const saveRef = useRef(save);
  useEffect(() => {
    saveRef.current = save;
  }, [save]);

  // --- live updates and the edit lease ----------------------------------------
  const flash = useCallback((text: string) => {
    setNotice(text);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), NOTICE_MS);
  }, []);

  // Someone else saved. With nothing unsaved here, show their version (the
  // previous state stays on the undo stack); otherwise the next save hits
  // the 409 and the conflict banner decides.
  const pull = useCallback(async (by?: string) => {
    const c = await api.canvas(canvasId);
    if (c.revision <= revision.current || inConflict.current) return;
    if (serialize() !== lastSaved.current) return;
    undo.current.push(current.current);
    redo.current = [];
    revision.current = c.revision;
    setHead(c.revision);
    setLease(c.lease);
    lastSaved.current = current.current = apply(c.data);
    setStatus("saved");
    if (by) flash(`Updated by ${by}`);
  }, [canvasId, apply, serialize, setStatus, flash]);

  const pullRef = useRef(pull);
  useEffect(() => {
    pullRef.current = pull;
  }, [pull]);

  useEffect(() => {
    if (!loaded) return;
    const es = new EventSource(`/api/canvases/${canvasId}/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as CanvasEvent;
      if (ev.type === "hello") {
        setLease(ev.lease);
        if (ev.revision > revision.current) void pullRef.current();
      } else if (ev.type === "lease") {
        setLease(ev.lease);
      } else if (ev.type === "revision") {
        const mine = ev.client.startsWith("ui:") && ev.client.endsWith(":" + CLIENT_ID);
        if (!mine && ev.revision > revision.current) void pullRef.current(ev.by);
      }
    };
    return () => es.close();
  }, [canvasId, loaded]);

  // Leases lapse without an event; check again when this one should have.
  useEffect(() => {
    blocked.current = !!otherLease;
    if (!otherLease) {
      if (loaded && serialize() !== lastSaved.current && !inConflict.current) void saveRef.current();
      return;
    }
    const t = window.setTimeout(() => {
      api.lease(canvasId).then((r) => setLease(r.lease), () => undefined);
    }, otherLease.seconds_left * 1000 + 500);
    return () => window.clearTimeout(t);
  }, [otherLease, canvasId, loaded, serialize]);

  useEffect(() => {
    const bye = () => releaseOnUnload(canvasId);
    window.addEventListener("pagehide", bye);
    return () => {
      window.removeEventListener("pagehide", bye);
      void api.releaseLease(canvasId).catch(() => undefined);
    };
  }, [canvasId]);

  const takeOver = async () => {
    try {
      const r = await api.takeLease(canvasId, true);
      setLease(r.lease);
      blocked.current = false;
      // Whatever they wrote while holding it comes first.
      await pull();
      if (serialize() !== lastSaved.current) void save();
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e));
    }
  };

  // Every settled change: record history, then save.
  useEffect(() => {
    if (!loaded) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const s = serialize(nodes, edges);
      if (s !== current.current) {
        undo.current.push(current.current);
        if (undo.current.length > HISTORY_LIMIT) undo.current.shift();
        redo.current = [];
        current.current = s;
      }
      if (s !== lastSaved.current) {
        if (!inConflict.current) setStatus("unsaved");
        void save();
      }
    }, SAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer.current);
  }, [nodes, edges, loaded, serialize, save, setStatus]);

  const flush = useCallback(async () => {
    window.clearTimeout(timer.current);
    if (!loaded) return true;
    current.current = serialize();
    return save();
  }, [loaded, serialize, save]);

  // --- versions (HistoryPanel.tsx) ----------------------------------------------
  const openPreview = useCallback(async (rev: number) => {
    try {
      const r = await api.revision(canvasId, rev);
      const d = diff(r.data, JSON.parse(serialize()));
      const mark = new Map([...d.nodes.added.map((id) => [id, "nw-diff-add"] as const),
        ...d.nodes.changed.map((id) => [id, "nw-diff-change"] as const)]);
      const f = toFlow(r.data);
      setPreview({
        rev, at: r.created_at, by: r.by, label: r.label, data: r.data, edges: f.edges, summary: summary(d),
        nodes: f.nodes.map((n) => (mark.has(n.id) ? { ...n, className: mark.get(n.id) } : n)),
      });
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e));
    }
  }, [canvasId, serialize, flash]);

  // Restoring is an ordinary edit: one Ctrl+Z away, saved as a new revision
  // that records where it came from.
  const restore = () => {
    if (!preview) return;
    const now = serialize();
    if (now !== current.current) undo.current.push(current.current);
    undo.current.push(now);
    redo.current = [];
    restoredFrom.current = preview.rev;
    current.current = apply(preview.data);
    if (current.current === lastSaved.current) restoredFrom.current = undefined;
    setPreview(null);
    flash(`Restored ${preview.label ? `“${preview.label}”` : `r${preview.rev}`} — Ctrl+Z undoes it.`);
  };

  const saveVersion = async () => {
    const label = prompt("Name this version", "")?.trim();
    if (!label) return;
    if (!(await flush())) {
      flash("Couldn't save the latest changes, so no version was named.");
      return;
    }
    try {
      await api.nameRevision(canvasId, revision.current, label);
      flash(`Saved version “${label}”.`);
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e));
    }
  };

  useImperativeHandle(ref, () => ({
    flush,
    exportDoc: () => (loaded ? JSON.parse(serialize()) : null),
    focusNode: (id: string) => {
      if (!showNode(id)) flash(`That link points at node ${id}, which isn't on this tab any more.`);
    },
  }), [flush, loaded, serialize, showNode, flash]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (loaded && serialize() !== lastSaved.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [loaded, serialize]);

  useEffect(() => () => {
    window.clearTimeout(timer.current);
    window.clearTimeout(retry.current);
    window.clearTimeout(noticeTimer.current);
  }, []);

  const resolveConflict = async (keepMine: boolean) => {
    if (!conflict) return;
    revision.current = conflict.revision;
    setHead(conflict.revision);
    inConflict.current = false;
    setConflict(null);
    if (keepMine) {
      await save();
    } else {
      const s = apply(conflict.data);
      lastSaved.current = current.current = s;
      setStatus("saved");
    }
  };

  // --- history ----------------------------------------------------------------
  const step = useCallback((from: React.MutableRefObject<string[]>, to: React.MutableRefObject<string[]>) => {
    // An edit still inside the debounce window becomes its own history entry
    // first, so undo never skips it.
    const now = serialize();
    if (now !== current.current) {
      undo.current.push(current.current);
      redo.current = [];
      current.current = now;
    }
    const prev = from.current.pop();
    if (prev === undefined) return;
    to.current.push(current.current);
    current.current = apply(JSON.parse(prev));
  }, [apply, serialize]);

  // --- editing helpers --------------------------------------------------------
  const snapTo = (v: number) => (snap.on ? Math.round(v / snap.size) * snap.size : Math.round(v));

  // Where a click-inserted w×h box goes: the free grid slot nearest the view
  // centre (so repeated clicks don't stack), panned into view if need be.
  const freeSpot = (w: number, h: number) => {
    const r = wrapper.current!.getBoundingClientRect();
    const c = flow.screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
    const base = { x: c.x - w / 2, y: c.y - h / 2 };
    const boxes = flow.getNodes().map((n) => ({
      x: n.position.x, y: n.position.y,
      w: n.measured?.width ?? n.width ?? 0, h: n.measured?.height ?? n.height ?? 0,
    }));
    const hits = (p: { x: number; y: number }) =>
      boxes.some((b) => p.x < b.x + b.w + 20 && p.x + w + 20 > b.x && p.y < b.y + b.h + 20 && p.y + h + 20 > b.y);
    const slots: { x: number; y: number; d: number }[] = [];
    for (let i = -6; i <= 6; i++) for (let j = -6; j <= 6; j++) {
      slots.push({ x: base.x + i * (w + 40), y: base.y + j * (h + 40), d: Math.hypot(i * (w + 40), j * (h + 40)) });
    }
    slots.sort((a, b) => a.d - b.d);
    const pos = slots.find((s) => !hits(s)) ?? base;
    const tl = flow.screenToFlowPosition({ x: r.left, y: r.top });
    const br = flow.screenToFlowPosition({ x: r.right, y: r.bottom });
    if (pos.x < tl.x || pos.y < tl.y || pos.x + w > br.x || pos.y + h > br.y) {
      setTimeout(() => flow.setCenter(pos.x + w / 2, pos.y + h / 2, { zoom: flow.getZoom(), duration: 300 }), 0);
    }
    return pos;
  };

  const addNode = (type: "text" | "group" | "link" | "file", at?: { x: number; y: number }, file?: string) => {
    const [w, h] = SIZES[type];
    const pos = at ?? freeSpot(w, h);
    const raw: Record<string, any> = { id: newId(), type, x: snapTo(pos.x), y: snapTo(pos.y), width: w, height: h };
    if (type === "text") raw.text = "";
    if (type === "group") raw.label = "Group";
    if (type === "link") raw.url = "https://";
    if (type === "file") raw.file = file ?? "";
    const node: CNode = {
      id: raw.id, type, position: { x: raw.x, y: raw.y }, width: w, height: h,
      zIndex: type === "group" ? 0 : 1, data: { raw }, selected: true,
    };
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), node]);
  };

  // A schema node for `source` (a sample, or a dropped file), parsed by the server.
  const addSchema = async (fmt: SchemaFormat, source = SAMPLES[fmt], at?: { x: number; y: number }) => {
    let r: SchemaParse;
    try {
      r = await api.parseSchema(fmt, source);
    } catch (e) {
      flash(`Couldn't read that schema: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    const longest = Math.max(...source.split("\n").map((l) => l.length));
    const w = Math.min(640, Math.max(260, Math.round(longest * 7.3) + 24));
    const pos = at ?? freeSpot(w, r.height);
    const raw: Record<string, any> = {
      id: newId(), type: "text", schema: fmt, text: r.text, ports: r.ports,
      x: snapTo(pos.x), y: snapTo(pos.y), width: w, height: r.height,
    };
    const node: CNode = {
      id: raw.id, type: "text", position: { x: raw.x, y: raw.y }, width: w, height: r.height, zIndex: 1, data: { raw }, selected: true,
    };
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), node]);
    if (r.error) flash(`Added, but it doesn't parse yet: ${r.error}`);
  };

  // An icon from the palette: added to the one selected text node if it has
  // no icon yet (so clicking several icons in a row adds several nodes),
  // otherwise a new icon node (caption = the icon's name) at `at` or in a free
  // spot. The node takes the icon's ports when it has none, and its colour mode.
  // `at` (from a drop) is where the icon's centre goes.
  const placeIcon = (icon: Icon, at?: { x: number; y: number }) => {
    const iconFields = (raw: Record<string, any>) => {
      const next: Record<string, any> = withAttr({ ...raw, icon: icon.file }, "iconColors", icon.tinted ? "" : "original");
      if (icon.ports.length && !portsOf(raw).length) next.ports = orient(icon.ports, orientationOf(raw));
      return next;
    };
    // An icon with ports is a symbol (a schematic part, design §15): no border,
    // the caption under it, and square, so its pins sit where its leads end.
    // Symbols always make a new node; plain icons can go on the selected text box.
    const symbol = icon.ports.length > 0;
    const target = !at && !symbol && selNodes.length === 1 && selEdges.length === 0
      && selNodes[0].data.raw.type === "text" && !selNodes[0].data.raw.icon ? selNodes[0] : null;
    if (target) {
      setNodes((ns) => ns.map((n) => (n.id === target.id ? { ...n, data: { raw: iconFields(n.data.raw) } } : n)));
      return;
    }
    const side = symbol ? icon.size ?? 80 : 120;
    const [w, h] = [side, side];
    const pos = at ? { x: at.x - w / 2, y: at.y - h / 2 } : freeSpot(w, h);
    let raw = iconFields({
      id: newId(), type: "text", text: symbol ? "" : icon.name, x: snapTo(pos.x), y: snapTo(pos.y), width: w, height: h,
    });
    if (symbol) raw = withAttr(raw, "border", "invisible");
    const node: CNode = {
      id: raw.id, type: "text", position: { x: raw.x, y: raw.y }, width: w, height: h, zIndex: 1, data: { raw }, selected: true,
    };
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), node]);
  };

  // A template is a JSON Canvas fragment starting at (0, 0): copy it with
  // fresh ids, its top-left at `at` (flow coordinates) or in a free spot.
  const insertTemplate = (t: Template, at?: { x: number; y: number }) => {
    const src: any[] = t.data.nodes ?? [];
    if (src.length === 0) return;
    const w = Math.max(...src.map((n) => n.x + n.width)), h = Math.max(...src.map((n) => n.y + n.height));
    const pos = at ?? freeSpot(w, h);
    const ox = snapTo(pos.x), oy = snapTo(pos.y);
    const ids = new Map<string, string>();
    const nodesRaw = src.map((n) => {
      const id = newId();
      ids.set(n.id, id);
      return { ...structuredClone(n), id, x: n.x + ox, y: n.y + oy };
    });
    const edgesRaw = (t.data.edges ?? []).map((e: any) => ({
      ...structuredClone(e), id: newId(), fromNode: ids.get(e.fromNode), toNode: ids.get(e.toNode),
    }));
    const f = toFlow({ nodes: nodesRaw, edges: edgesRaw });
    const added = f.nodes.map((n) => ({ ...n, selected: true }));
    setNodes((ns) => [
      ...added.filter((n) => n.type === "group"),
      ...ns.map((n) => ({ ...n, selected: false })),
      ...added.filter((n) => n.type !== "group"),
    ]);
    setEdges((es) => [...es.map((e) => ({ ...e, selected: false })), ...f.edges]);
  };

  // Upload files into the workspace and add a file node for each: images at
  // their aspect ratio (at most 480×360), anything else as a download card.
  const uploadFiles = async (files: File[], at?: { x: number; y: number }) => {
    if (!attachmentLimit || readOnly || !workspaceId.current || files.length === 0) return;
    let pos = at;
    for (const f of files) {
      if (f.size > attachmentLimit) {
        flash(`${f.name} is over the ${Math.round(attachmentLimit / 1048576)} MB limit.`);
        continue;
      }
      flash(`Uploading ${f.name}…`);
      let a;
      try {
        a = await api.uploadAttachment(workspaceId.current, f);
      } catch (e) {
        const detail = e instanceof ApiError ? e.body?.detail ?? `error ${e.status}` : String(e);
        flash(`Couldn't upload ${f.name}: ${detail}`);
        continue;
      }
      let [w, h] = [260, 70];
      if (a.image) {
        try {
          const b = await createImageBitmap(f);
          const k = Math.min(1, 480 / b.width, 360 / b.height);
          [w, h] = [Math.max(40, Math.round(b.width * k)), Math.max(30, Math.round(b.height * k))];
          b.close();
        } catch {
          [w, h] = [320, 240];
        }
      }
      const p = pos ?? freeSpot(w, h);
      const raw: Record<string, any> = { id: newId(), type: "file", file: a.file, x: snapTo(p.x), y: snapTo(p.y), width: w, height: h };
      const node: CNode = {
        id: raw.id, type: "file", position: { x: raw.x, y: raw.y }, width: w, height: h, zIndex: 1, data: { raw }, selected: true,
      };
      setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), node]);
      if (pos) pos = { x: pos.x + 40, y: pos.y + 40 };
      flash(`Added ${f.name}`);
    }
  };

  // Files: schema files become schema nodes (always); anything else is an attachment (when enabled).
  const draggingFiles = (e: React.DragEvent) => !readOnly && e.dataTransfer.types.includes("Files");

  const onDragOver = (e: React.DragEvent) => {
    if (draggingFiles(e)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      if (!dropping) setDropping(true);
      return;
    }
    if (readOnly || !(e.dataTransfer.types.includes(DRAG_TYPE) || e.dataTransfer.types.includes(ICON_DRAG_TYPE))) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  const onDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Element | null)) setDropping(false);
  };

  const onDrop = async (e: React.DragEvent) => {
    setDropping(false);
    if (draggingFiles(e) && e.dataTransfer.files.length > 0) {
      e.preventDefault();
      let at = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const files = [...e.dataTransfer.files];
      for (const f of files) {
        const fmt = formatForFile(f.name);
        if (!fmt) continue;
        await addSchema(fmt, await f.text(), at);
        at = { x: at.x + 40, y: at.y + 40 };
      }
      const rest = files.filter((f) => !formatForFile(f.name));
      if (rest.length && !attachmentLimit) flash("File attachments aren't enabled on this server.");
      else await uploadFiles(rest, at);
      return;
    }
    const iconData = e.dataTransfer.getData(ICON_DRAG_TYPE);
    if (iconData && !readOnly) {
      e.preventDefault();
      const at = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      placeIcon(JSON.parse(iconData) as Icon, at);
      return;
    }
    const id = e.dataTransfer.getData(DRAG_TYPE);
    if (readOnly || !id) return;
    e.preventDefault();
    const at = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const t = (await api.templates()).templates.find((x) => x.id === id);
    if (t) insertTemplate(t, at);
  };

  const saveSelectionAsTemplate = async () => {
    const ids = new Set(selNodes.map((n) => n.id));
    const between = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    const kind = selNodes.length === 1 ? "stencil" : "fragment";
    const name = prompt(kind === "stencil" ? "Name this shape" : "Name this snippet")?.trim();
    if (!name) return;
    try {
      await api.createTemplate(name, kind, toCanvas(selNodes, between));
      setTplReload((n) => n + 1);
      setPaletteOpen(true);
      flash(`Saved "${name}" to your templates`);
    } catch (err) {
      flash(err instanceof Error ? err.message : String(err));
    }
  };

  const savePage = async () => {
    const name = prompt("Name this page template")?.trim();
    if (!name) return;
    const { nodes: n, edges: e } = JSON.parse(serialize());
    await api.createTemplate(name, "page", { nodes: n, edges: e });
    flash(`Saved "${name}" as a page template`);
  };

  const updateEdgeRaw = useCallback((id: string, patch: Record<string, unknown>) => {
    setEdges((es) => es.map((e) => {
      if (e.id !== id) return e;
      const raw = { ...e.data!.raw, ...patch };
      for (const k of Object.keys(patch)) if (patch[k] === undefined) delete raw[k];
      return { ...e, data: { ...e.data, raw }, ...edgeVisual(raw) };
    }));
  }, [setEdges]);

  // An end's fields for a connection: fromSide/toSide, plus fromPort/toPort
  // when it was made to a port (ports.ts). Unset fields are removed.
  const ends = useCallback((c: Connection, base: Record<string, any>) => {
    const raw: Record<string, any> = {
      ...base, fromNode: c.source, toNode: c.target,
      ...endFields(flow.getNode(c.source)?.data.raw, c.sourceHandle, "from"),
      ...endFields(flow.getNode(c.target)?.data.raw, c.targetHandle, "to"),
    };
    for (const k of Object.keys(raw)) if (raw[k] === undefined) delete raw[k];
    return raw;
  }, [flow]);

  const onConnect = useCallback((c: Connection) => {
    const raw = ends(c, { id: newId() });
    // A wire between schematic parts has no arrowhead (wires.ts).
    if (isWireEdge(raw, flow.getNode(c.source)?.data.raw, flow.getNode(c.target)?.data.raw)) raw.toEnd = "none";
    setEdges((es) => addEdge({ ...c, id: raw.id, data: { raw }, ...edgeVisual(raw) }, es));
  }, [setEdges, ends, flow]);

  const onReconnect = useCallback((old: Edge, c: Connection) => {
    setEdges((es) => {
      const next = reconnectEdge(old, c, es as Edge[]) as CEdge[];
      return next.map((e) => e.id !== old.id ? e : {
        ...e,
        data: { raw: ends(c, (old as CEdge).data!.raw) },
      });
    });
  }, [setEdges, ends]);

  // Replace a node's ports; its lines follow a renamed port, take a moved
  // port's side, and fall back to their side (flagged) when theirs is gone.
  const setPorts = useCallback((nodeId: string, ports: Port[], renamed?: [string, string],
    patch: Record<string, any> = {}) => {
    const node = flow.getNode(nodeId) as CNode | undefined;
    if (!node) return;
    const raw: Record<string, any> = { ...node.data.raw, ...patch, ports };
    if (!ports.length) delete raw.ports;
    setNodes((ns) => ns.map((n) => (n.id !== nodeId ? n
      : { ...n, data: { raw }, ...(patch.height ? { height: patch.height } : {}) })));
    setEdges((es) => es.map((e) => {
      if (e.source !== nodeId && e.target !== nodeId) return e;
      const er = { ...e.data!.raw };
      for (const [nk, pk, sk] of [["fromNode", "fromPort", "fromSide"], ["toNode", "toPort", "toSide"]]) {
        if (er[nk] !== nodeId || typeof er[pk] !== "string") continue;
        if (renamed && er[pk] === renamed[0]) er[pk] = renamed[1];
        const p = ports.find((x) => x.id === er[pk]);
        if (p) er[sk] = p.side;
      }
      const from = er.fromNode === nodeId ? raw : flow.getNode(er.fromNode)?.data.raw;
      const to = er.toNode === nodeId ? raw : flow.getNode(er.toNode)?.data.raw;
      return { ...e, ...edgeEnds(er, from as Record<string, any>, to as Record<string, any>) };
    }));
  }, [flow, setNodes, setEdges]);

  // A schema node's parse (schemas.py): new text, height and field ports; its lines follow.
  const applySchema = useCallback((nodeId: string, r: SchemaParse) => {
    setPorts(nodeId, r.ports, undefined, { text: r.text, height: r.height });
  }, [setPorts]);

  // JSON Canvas groups don't own their nodes; like Obsidian, dragging a group
  // carries whatever lies inside it when the drag starts.
  const onNodeDragStart = useCallback((_: unknown, node: Node) => {
    if (node.type !== "group") return;
    const all = flow.getNodes();
    const g = { x: node.position.x, y: node.position.y, w: node.width ?? 0, h: node.height ?? 0 };
    const members = new Map<string, { x: number; y: number }>();
    for (const n of all) {
      if (n.id === node.id || n.selected) continue;
      const w = n.width ?? n.measured?.width ?? 0, h = n.height ?? n.measured?.height ?? 0;
      if (n.position.x >= g.x && n.position.y >= g.y && n.position.x + w <= g.x + g.w && n.position.y + h <= g.y + g.h) {
        members.set(n.id, { ...n.position });
      }
    }
    groupDrag.current = { id: node.id, start: { ...node.position }, members };
  }, [flow]);

  const onNodeDrag = useCallback((_: unknown, node: Node) => {
    const gd = groupDrag.current;
    if (!gd || gd.id !== node.id || gd.members.size === 0) return;
    const dx = node.position.x - gd.start.x, dy = node.position.y - gd.start.y;
    setNodes((ns) => ns.map((n) => {
      const p = gd.members.get(n.id);
      return p ? { ...n, position: { x: p.x + dx, y: p.y + dy } } : n;
    }));
  }, [setNodes]);

  const onNodeDragStop = useCallback(() => {
    groupDrag.current = null;
  }, []);

  const onPaneDoubleClick = (e: ReactMouseEvent) => {
    if (readOnly) return;
    if (!(e.target as HTMLElement).classList.contains("react-flow__pane")) return;
    const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    addNode("text", { x: p.x - SIZES.text[0] / 2, y: p.y - SIZES.text[1] / 2 });
  };

  const onEdgeDoubleClick = (e: ReactMouseEvent, edge: Edge) => {
    if (readOnly) return;
    const r = wrapper.current!.getBoundingClientRect();
    setLabelEdit({ id: edge.id, x: e.clientX - r.left, y: e.clientY - r.top, value: (edge as CEdge).data?.raw.label ?? "" });
  };

  const commitLabel = () => {
    if (!labelEdit) return;
    updateEdgeRaw(labelEdit.id, { label: labelEdit.value.trim() || undefined });
    setLabelEdit(null);
  };

  const selNodes = nodes.filter((n) => n.selected);
  const selEdges = edges.filter((e) => e.selected);

  const setColor = (color: string | undefined) => {
    const ids = new Set(selNodes.map((n) => n.id));
    setNodes((ns) => ns.map((n) => {
      if (!ids.has(n.id)) return n;
      const raw = { ...n.data.raw, color };
      if (color === undefined) delete raw.color;
      return { ...n, data: { raw } };
    }));
    for (const e of selEdges) updateEdgeRaw(e.id, { color });
  };

  const setNodeAttr = (key: string, value: string, only?: (n: CNode) => boolean) => {
    const ids = new Set(selNodes.filter((n) => !only || only(n)).map((n) => n.id));
    setNodes((ns) => ns.map((n) => ids.has(n.id) ? { ...n, data: { raw: withAttr(n.data.raw, key, value) } } : n));
    // A net label's one pin is its point (design §15).
    if (key === "shape" && value === "net") {
      for (const n of selNodes) if (ids.has(n.id) && !portsOf(n.data.raw).length) setPorts(n.id, [{ ...NET_PORT }], undefined, withAttr(n.data.raw, "shape", "net"));
    }
  };

  // Turn or flip the selected symbols (and flip net labels) on screen; their
  // ports move with them and their wires follow (ports.ts turned/flipped).
  const reorient = (how: (o: Orientation, ps: Port[]) => [Orientation, Port[]]) => {
    for (const n of selNodes) {
      const net = attr(n.data.raw, "shape") === "net" && how === flipped;
      if (!isSymbol(n.data.raw) && !net) continue;
      const [o, ps] = how(orientationOf(n.data.raw), portsOf(n.data.raw));
      let raw = withAttr(n.data.raw, "rotate", o.rotate ? String(o.rotate) : "");
      raw = withAttr(raw, "mirror", o.mirror ? "horizontal" : "");
      setPorts(n.id, ps, undefined, raw);
    }
  };

  const addNetLabel = () => {
    const name = prompt("Net name", "VCC")?.trim();
    if (!name) return;
    const [w, h] = [Math.max(60, 24 + name.length * 9), 30];
    const pos = freeSpot(w, h);
    const raw = withAttr(withAttr({
      id: newId(), type: "text", text: name, x: snapTo(pos.x), y: snapTo(pos.y), width: w, height: h, ports: [{ ...NET_PORT }],
    }, "shape", "net"), "textAlign", "center");
    const node: CNode = {
      id: raw.id, type: "text", position: { x: raw.x, y: raw.y }, width: w, height: h, zIndex: 1, data: { raw }, selected: true,
    };
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), node]);
  };

  const setEdgeAttr = (key: string, value: string) => {
    const ids = new Set(selEdges.map((e) => e.id));
    setEdges((es) => es.map((e) => {
      if (!ids.has(e.id)) return e;
      const raw = withAttr(e.data!.raw, key, value);
      return { ...e, data: { ...e.data, raw }, ...edgeVisual(raw) };
    }));
  };

  const deleteSelection = () => {
    void flow.deleteElements({ nodes: selNodes, edges: selEdges });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, [contenteditable]")) return;
      const mod = e.ctrlKey || e.metaKey;
      if (readOnly && mod && "zy".includes(e.key.toLowerCase())) return;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) step(redo, undo);
        else step(undo, redo);
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        step(redo, undo);
      } else if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void flush();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, flush, readOnly]);

  // Pasting an image (e.g. a screenshot) uploads it, unless typing in a field.
  const uploadRef = useRef(uploadFiles);
  useEffect(() => {
    uploadRef.current = uploadFiles;
  });
  useEffect(() => {
    if (readOnly || !attachmentLimit) return;
    const onPaste = (e: ClipboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.closest("input, textarea, select") || t.isContentEditable)) return;
      const files = [...(e.clipboardData?.files ?? [])];
      if (files.length === 0) return;
      e.preventDefault();
      void uploadRef.current(files);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [readOnly, attachmentLimit]);

  useEffect(() => {
    localStorage.setItem("nw.snap", JSON.stringify(snap));
  }, [snap]);

  useEffect(() => {
    localStorage.setItem("nw.palette", paletteOpen ? "1" : "0");
  }, [paletteOpen]);

  if (loadError) return <div className="center-msg">Couldn't open this canvas: {loadError}</div>;

  const oneEdge = selEdges.length === 1 && selNodes.length === 0 ? selEdges[0] : null;
  const oneNode = selNodes.length === 1 && selEdges.length === 0 ? selNodes[0] : null;
  const nodeRaws = selNodes.map((n) => n.data.raw);
  const textRaws = nodeRaws.filter((r) => r.type === "text");
  const symbolCount = nodeRaws.filter(isSymbol).length;
  const netLabelCount = textRaws.filter((r) => attr(r, "shape") === "net").length;
  // One net label selected: the others on its net light up, and the toolbar counts them.
  const net = oneNode && attr(oneNode.data.raw, "shape") === "net" ? netName(oneNode.data.raw) : null;
  const netCount = net === null ? 0
    : nodes.filter((n) => attr(n.data.raw, "shape") === "net" && netName(n.data.raw) === net).length;
  const edgeRaws = selEdges.map((e) => e.data!.raw);

  return (
    <ReadOnly.Provider value={readOnly}>
    <SchemaOps.Provider value={readOnly ? null : applySchema}>
    <SelectedNet.Provider value={net}>
    <div className={"editor" + (readOnly ? " readonly" : "") + (paletteOpen && !preview ? " with-palette" : "")
      + (historyOpen ? " with-history" : "") + (dropping ? " drop-files" : "")}
      ref={wrapper} onDoubleClick={onPaneDoubleClick} onDragOver={onDragOver} onDragLeave={onDragLeave}
      onDrop={(e) => void onDrop(e)}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onReconnect={onReconnect}
        onNodeDragStart={onNodeDragStart}
        onNodeDrag={onNodeDrag}
        onNodeDragStop={onNodeDragStop}
        onEdgeDoubleClick={onEdgeDoubleClick}
        connectionMode={ConnectionMode.Loose}
        snapToGrid={snap.on}
        snapGrid={[snap.size, snap.size]}
        zoomOnDoubleClick={false}
        deleteKeyCode={readOnly ? null : ["Delete", "Backspace"]}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable={!readOnly}
        edgesReconnectable={!readOnly}
        multiSelectionKeyCode={["Shift", "Meta", "Control"]}
        elevateNodesOnSelect={false}
        elevateEdgesOnSelect
        minZoom={0.05}
        maxZoom={4}
        colorMode="system"
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={snap.on ? BackgroundVariant.Dots : BackgroundVariant.Lines}
          gap={snap.on ? snap.size : 40}
          size={snap.on ? 1.5 : 0.5}
        />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
        {!readOnly && <Panel position="top-left" className="toolbar">
          <button onClick={() => addNode("text")} title="Add a text card (or double-click the canvas)">+ Text</button>
          <button onClick={() => addNode("group")}>+ Group</button>
          <button onClick={() => addNode("link")}>+ Link</button>
          {attachmentLimit !== undefined && (
            <>
              <button onClick={() => fileInput.current?.click()}
                title="Upload images or files (you can also drop or paste them onto the canvas)">+ File</button>
              <input ref={fileInput} type="file" multiple hidden onChange={(e) => {
                const fs = [...(e.target.files ?? [])];
                e.target.value = "";
                void uploadFiles(fs);
              }} />
            </>
          )}
          {tabLinks.tabs.length > 1 && (
            <select value="" aria-label="Link to tab" title="Add a card that opens another tab of this workspace"
              onChange={(e) => {
                const t = tabLinks.tabs.find((x) => x.id === e.target.value);
                if (t) addNode("file", undefined, canvasFile(t.name));
              }}>
              <option value="">+ Tab link…</option>
              {tabLinks.tabs.filter((t) => t.id !== canvasId).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          )}
          <select value="" title="A schema (Avro, Protobuf, JSON, YAML, SQL) with a connection point per field; or drop a schema file"
            onChange={(e) => { const f = e.target.value as SchemaFormat; if (f) void addSchema(f); }}>
            <option value="">+ Schema…</option>
            {SCHEMA_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select>
          <button className={paletteOpen ? "on" : ""} onClick={() => setPaletteOpen(!paletteOpen)}
            title="Shapes, snippets and page templates">Templates</button>
          <span className="sep" />
          <button onClick={() => step(undo, redo)} title="Undo (Ctrl+Z)">↶</button>
          <button onClick={() => step(redo, undo)} title="Redo (Ctrl+Shift+Z)">↷</button>
          <span className="sep" />
          <label className="check" title="Snap nodes to the grid while dragging">
            <input type="checkbox" checked={snap.on} onChange={(e) => setSnap({ ...snap, on: e.target.checked })} /> Snap
          </label>
          <select value={snap.size} disabled={!snap.on} onChange={(e) => setSnap({ ...snap, size: Number(e.target.value) })} title="Grid size">
            {[10, 20, 40].map((s) => <option key={s} value={s}>{s}px</option>)}
          </select>
        </Panel>}
        {!readOnly && (selNodes.length > 0 || selEdges.length > 0) && (
          <Panel position="top-center" className="toolbar selbar">
            <span className="muted">Colour</span>
            <button className="swatch none" title="Default" onClick={() => setColor(undefined)} />
            {Object.entries(PRESETS).map(([k, c]) => (
              <button key={k} className="swatch" style={{ background: c }} title={`Preset ${k}`} onClick={() => setColor(k)} />
            ))}
            <input type="color" title="Custom colour" onChange={(e) => setColor(e.target.value)} />
            {textRaws.length > 0 && (
              <>
                <span className="sep" />
                {/* A symbol's shape is its drawing, and its caption is centred under it. */}
                {textRaws.some((r) => !isSymbol(r)) && <>
                  <Pick title="Shape" options={NODE_SHAPES} value={common(textRaws.filter((r) => !isSymbol(r)), "shape")}
                    onChange={(v) => setNodeAttr("shape", v, (n) => n.data.raw.type === "text" && !isSymbol(n.data.raw))} />
                  <Pick title="Text alignment" options={TEXT_ALIGN} value={common(textRaws.filter((r) => !isSymbol(r)), "textAlign")}
                    onChange={(v) => setNodeAttr("textAlign", v, (n) => n.data.raw.type === "text" && !isSymbol(n.data.raw))} />
                </>}
                {textRaws.some((r) => r.icon) && <>
                  <Pick title="Icon colours" options={ICON_COLORS} value={common(textRaws.filter((r) => r.icon), "iconColors")}
                    onChange={(v) => setNodeAttr("iconColors", v, (n) => !!n.data.raw.icon)} />
                  <button title="Remove the icon, keeping the text" onClick={() => {
                    const ids = new Set(selNodes.filter((n) => n.data.raw.icon).map((n) => n.id));
                    setNodes((ns) => ns.map((n) => {
                      if (!ids.has(n.id)) return n;
                      const raw = withAttr({ ...n.data.raw }, "iconColors", "");
                      delete raw.icon;
                      return { ...n, data: { raw } };
                    }));
                  }}>Remove icon</button>
                </>}
              </>
            )}
            {nodeRaws.length > 0 && (
              <Pick title="Border" options={NODE_BORDERS} value={common(nodeRaws, "border")}
                onChange={(v) => setNodeAttr("border", v)} />
            )}
            {edgeRaws.length > 0 && (
              <>
                <span className="sep" />
                <Pick title="Line style" options={EDGE_PATHS} value={common(edgeRaws, "path")}
                  onChange={(v) => setEdgeAttr("path", v)} />
                <Pick title="Line width" options={LINE_WIDTHS} value={common(edgeRaws, "lineWidth")}
                  onChange={(v) => setEdgeAttr("lineWidth", v)} />
                <Pick title="Routing" options={EDGE_ROUTES} value={common(edgeRaws, "pathfindingMethod")}
                  onChange={(v) => setEdgeAttr("pathfindingMethod", v)} />
                {edgeRaws.some((r) => attr(r, "pathfindingMethod") !== "direct") && (
                  <Pick title="Corner radius (right-angle routes and detours around nodes)"
                    options={CORNER_RADII} value={common(edgeRaws, "cornerRadius")}
                    onChange={(v) => setEdgeAttr("cornerRadius", v)} />
                )}
                <Pick title="Arrowhead" options={EDGE_ARROWS} value={common(edgeRaws, "arrow")}
                  onChange={(v) => setEdgeAttr("arrow", v)} />
              </>
            )}
            {oneEdge && (
              <>
                <span className="sep" />
                <label className="check">
                  <input type="checkbox" checked={oneEdge.data!.raw.fromEnd === "arrow"}
                    onChange={(e) => updateEdgeRaw(oneEdge.id, { fromEnd: e.target.checked ? "arrow" : undefined })} /> ◀
                </label>
                <label className="check">
                  <input type="checkbox" checked={(oneEdge.data!.raw.toEnd ?? "arrow") === "arrow"}
                    onChange={(e) => updateEdgeRaw(oneEdge.id, { toEnd: e.target.checked ? undefined : "none" })} /> ▶
                </label>
                <button onClick={(e) => onEdgeDoubleClick(e, oneEdge)}>Label…</button>
              </>
            )}
            {symbolCount + netLabelCount > 0 && (
              <>
                <span className="sep" />
                {symbolCount > 0 && <button onClick={() => reorient(turned)} title="Turn 90° clockwise; wires stay on their pins">⟳ Rotate</button>}
                <button onClick={() => reorient(flipped)} title="Mirror left to right; wires stay on their pins">⇋ Flip</button>
              </>
            )}
            {net !== null && (
              <span className="muted" title="Wires on net labels with the same name are connected">
                net “{oneNode!.data.raw.text}”: {netCount} label{netCount === 1 ? "" : "s"}
              </span>
            )}
            {oneNode && (
              <>
                <span className="sep" />
                <button onClick={() => setPortsOpen((v) => !v)} aria-pressed={portsOpen}
                  title="Named connection points on this node's sides">
                  Ports{portsOf(oneNode.data.raw).length ? ` (${portsOf(oneNode.data.raw).length})` : "…"}
                </button>
              </>
            )}
            <span className="sep" />
            {selNodes.length > 0 && <button onClick={() => void saveSelectionAsTemplate()}
              title="Keep the selected nodes (and the edges between them) as a reusable template">Save as template…</button>}
            <button onClick={deleteSelection} title="Delete (Del)">Delete</button>
          </Panel>
        )}
        {!readOnly && portsOpen && oneNode && (
          <Panel position="top-right">
            <PortsPanel ports={portsOf(oneNode.data.raw)} onClose={() => setPortsOpen(false)}
              onChange={(ps, renamed) => setPorts(oneNode.id, ps, renamed)} />
          </Panel>
        )}
        {conflict && (
          <Panel position="bottom-center" className="banner">
            This canvas was changed somewhere else since you opened it.
            <button onClick={() => void resolveConflict(false)}>Load their version</button>
            <button onClick={() => void resolveConflict(true)}>Keep mine</button>
          </Panel>
        )}
        {otherLease && !conflict && (
          <Panel position="bottom-center" className={"banner" + (otherLease.kind === "agent" ? " agent" : "")}>
            {otherLease.kind === "agent" ? "🤖 " : ""}<strong>{otherLease.label}</strong>&nbsp;is editing this canvas — view only.
            {status === "locked" && <span className="muted">Your last change is waiting to save.</span>}
            {canEdit && <button onClick={() => void takeOver()}>Take over</button>}
          </Panel>
        )}
        {!canEdit && !otherLease && (
          <Panel position="bottom-center" className="banner">You can view this canvas but not edit it.</Panel>
        )}
        {notice && <Panel position="bottom-left" className="banner notice">{notice}</Panel>}
        {status === "error" && (
          <Panel position="bottom-center" className="banner warn">Couldn't save — retrying…</Panel>
        )}
      </ReactFlow>
      <Markers edges={edges} />
      {preview && (
        <div className="preview-layer">
          <ReactFlowProvider key={preview.rev}>
            <ReadOnlyFlow nodes={preview.nodes} edges={preview.edges} colorMode="system" />
          </ReactFlowProvider>
          <div className="banner preview-banner">
            <span>
              <strong>{preview.label ? `“${preview.label}”` : `Revision ${preview.rev}`}</strong>
              <span className="muted"> · {when(preview.at)}{preview.by ? ` · ${preview.by}` : ""}</span>
              <br />
              {preview.rev === head ? "This is the current version." : preview.summary}
            </span>
            {writable && preview.rev !== head && (
              <button className="primary" onClick={restore}
                disabled={preview.summary === "Same as the current version."}>Restore</button>
            )}
            <button onClick={() => setPreview(null)}>Back to editing</button>
          </div>
        </div>
      )}
      {historyOpen && (
        <HistoryPanel canvasId={canvasId} head={head} canEdit={writable} previewing={preview?.rev ?? null}
          onPreview={(rev) => void openPreview(rev)} onSaveVersion={saveVersion}
          onClose={() => onCloseHistory?.()} />
      )}
      {paletteOpen && !preview && (
        <Palette editable={!readOnly} reloadKey={tplReload} onInsert={(t) => insertTemplate(t)}
          onIcon={(i) => placeIcon(i)} onNetLabel={addNetLabel}
          onSavePage={savePage} onClose={() => setPaletteOpen(false)} />
      )}
      {labelEdit && (
        <input
          className="label-edit"
          style={{ left: labelEdit.x, top: labelEdit.y }}
          autoFocus
          placeholder="Edge label"
          value={labelEdit.value}
          onChange={(e) => setLabelEdit({ ...labelEdit, value: e.target.value })}
          onBlur={commitLabel}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitLabel();
            if (e.key === "Escape") setLabelEdit(null);
          }}
        />
      )}
    </div>
    </SelectedNet.Provider>
    </SchemaOps.Provider>
    </ReadOnly.Provider>
  );
});
