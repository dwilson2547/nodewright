// Icon creator (design §13.2): draw an icon from basic shapes on a 100x100
// grid and put pins on its edges; pins become the icon's ports. The drawing
// is saved with the icon (`source`) so it can be edited again; the server
// validates the SVG made from it like any upload.
import { useCallback, useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { api, type Icon } from "./api";
import {
  arcGeometry, BOX, DEFAULT_STYLE, dragHandle, empty, handles, moved, nearestEdge, pinPoint, toSvg,
  type Drawing, type Kind, type Shape,
} from "./iconDraw";
import { nextPortId, SIDES, type Port, type Side } from "./ports";

type Tool = "select" | Kind | "pin";
type Sel = { kind: "shape" | "pin"; i: number } | null;
type Pt = { x: number; y: number };
type Drag =
  | { mode: "draw"; start: Pt }
  | { mode: "move"; start: Pt; orig: Shape }
  | { mode: "handle"; h: string; orig: Shape }
  | { mode: "pin" };

const TOOLS: [Tool, string, string][] = [
  ["select", "↖", "Select and move (V)"],
  ["rect", "▭", "Rectangle (R)"],
  ["ellipse", "◯", "Ellipse (E)"],
  ["line", "╱", "Line (L)"],
  ["polyline", "⌇", "Polyline: click points, double-click or Enter to finish (P)"],
  ["arc", "◠", "Arc: drag the chord, then drag its middle handle to bend it (A)"],
  ["text", "T", "Text (T)"],
  ["pin", "⊡", "Pin: click near an edge; pins become the icon's ports (N)"],
];
const KEYS: Record<string, Tool> = { v: "select", r: "rect", e: "ellipse", l: "line", p: "polyline", a: "arc", t: "text", n: "pin" };
const PAD = 8;

function ShapeEl({ s, hit, onDown }: { s: Shape; hit?: boolean; onDown?: (e: RPointerEvent) => void }) {
  const p = hit
    ? { stroke: "transparent", strokeWidth: Math.max(s.sw, 6), fill: s.fill ? "transparent" : "none", onPointerDown: onDown, style: { cursor: "move" } }
    : { stroke: s.color, strokeWidth: s.sw, fill: s.fill ? s.color : "none", pointerEvents: "none" as const };
  switch (s.kind) {
    case "rect": return <rect x={s.x} y={s.y} width={s.w} height={s.h} rx={s.r} {...p} />;
    case "ellipse": return <ellipse cx={s.cx} cy={s.cy} rx={s.rx} ry={s.ry} {...p} />;
    case "line": return <line x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} {...p} />;
    case "polyline": {
      const pts = s.points.map(([x, y]) => `${x},${y}`).join(" ");
      return s.closed ? <polygon points={pts} {...p} /> : <polyline points={pts} {...p} />;
    }
    case "arc": return <path d={arcGeometry(s).d} {...p} />;
    case "text":
      return (
        <text x={s.x} y={s.y} fontSize={s.size} fontFamily="sans-serif" textAnchor="middle" dominantBaseline="middle"
          fill={hit ? "transparent" : s.color} stroke={hit ? "transparent" : "none"} strokeWidth={hit ? 4 : 0}
          onPointerDown={hit ? onDown : undefined} style={hit ? { cursor: "move" } : { pointerEvents: "none" }}>{s.text}</text>
      );
  }
}

export function IconCreator({ icon, onSaved, onClose }: {
  icon?: Icon;
  onSaved: (icon: Icon) => void;
  onClose: () => void;
}) {
  const [drawing, setDrawing] = useState<Drawing>(empty);
  const [undo, setUndo] = useState<Drawing[]>([]);
  const [redo, setRedo] = useState<Drawing[]>([]);
  const [tool, setTool] = useState<Tool>("rect");
  const [sel, setSel] = useState<Sel>(null);
  const [draft, setDraft] = useState<Shape | null>(null);
  const [snap, setSnap] = useState(true);
  const [style, setStyle] = useState(DEFAULT_STYLE);
  const [name, setName] = useState(icon?.name ?? "");
  const [tinted, setTinted] = useState(icon?.tinted ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);
  const before = useRef<Drawing | null>(null);

  useEffect(() => {
    if (!icon) return;
    api.getIcon(icon.id).then((r) => {
      if (r.source) setDrawing(r.source as Drawing);
    }, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, [icon]);

  // Every change goes through here so undo has the state before it.
  const commit = useCallback((next: Drawing, prev?: Drawing) => {
    setUndo((u) => [...u.slice(-99), prev ?? drawing]);
    setRedo([]);
    setDrawing(next);
  }, [drawing]);
  const step = (from: Drawing[], to: (f: (d: Drawing[]) => Drawing[]) => void, setFrom: (f: (d: Drawing[]) => Drawing[]) => void) => {
    if (!from.length) return;
    const last = from[from.length - 1];
    setFrom((f) => f.slice(0, -1));
    to((t) => [...t, drawing]);
    setDrawing(last);
    setSel(null);
  };

  const sn = (v: number) => (snap ? Math.round(v / 5) * 5 : Math.round(v * 10) / 10);
  const toBox = (e: { clientX: number; clientY: number }): Pt => {
    const m = svg.current!.getScreenCTM()!.inverse();
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m);
    return { x: sn(p.x), y: sn(p.y) };
  };

  const setShape = (i: number, s: Shape, live = false) => {
    const next = { ...drawing, shapes: drawing.shapes.map((x, j) => (j === i ? s : x)) };
    if (live) setDrawing(next);
    else commit(next);
  };
  const setPin = (i: number, patch: Partial<Port>, live = false) => {
    const next = { ...drawing, pins: drawing.pins.map((p, j) => {
      if (j !== i) return p;
      const n = { ...p, ...patch };
      if (!n.label) delete n.label;
      return n;
    }) };
    if (live) setDrawing(next);
    else commit(next);
  };

  const newShape = (kind: Kind, p: Pt): Shape => {
    switch (kind) {
      case "rect": return { ...style, kind, x: p.x, y: p.y, w: 0, h: 0, r: 0 };
      case "ellipse": return { ...style, kind, cx: p.x, cy: p.y, rx: 0, ry: 0 };
      case "line": return { ...style, kind, x1: p.x, y1: p.y, x2: p.x, y2: p.y };
      case "arc": return { ...style, kind, x1: p.x, y1: p.y, x2: p.x, y2: p.y, bulge: 0.5 };
      case "polyline": return { ...style, kind, points: [[p.x, p.y], [p.x, p.y]], closed: false };
      case "text": return { ...style, fill: true, kind, x: p.x, y: p.y, text: "Text", size: 18 };
    }
  };

  const finishPolyline = () => {
    if (draft?.kind !== "polyline") return;
    const points = draft.points.slice(0, -1);
    setDraft(null);
    if (points.length >= 2) {
      commit({ ...drawing, shapes: [...drawing.shapes, { ...draft, points }] });
      setSel({ kind: "shape", i: drawing.shapes.length });
    }
    setTool("select");
  };

  const onBackgroundDown = (e: RPointerEvent) => {
    if (e.button !== 0) return;
    const p = toBox(e);
    if (tool === "select") { setSel(null); return; }
    if (tool === "pin") {
      const pin: Port = { id: nextPortId(drawing.pins), ...nearestEdge(p.x, p.y) };
      commit({ ...drawing, pins: [...drawing.pins, pin] });
      setSel({ kind: "pin", i: drawing.pins.length });
      setTool("select");
      return;
    }
    if (tool === "text") {
      commit({ ...drawing, shapes: [...drawing.shapes, newShape("text", p)] });
      setSel({ kind: "shape", i: drawing.shapes.length });
      setTool("select");
      return;
    }
    if (tool === "polyline") {
      if (draft?.kind === "polyline") {
        const pts = draft.points.slice(0, -1);
        setDraft({ ...draft, points: [...pts, [p.x, p.y], [p.x, p.y]] });
      } else {
        setDraft(newShape("polyline", p));
      }
      return;
    }
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { mode: "draw", start: p };
    setDraft(newShape(tool, p));
  };

  const onMove = (e: RPointerEvent) => {
    const p = toBox(e);
    const d = drag.current;
    if (!d) {
      if (draft?.kind === "polyline") {
        setDraft({ ...draft, points: [...draft.points.slice(0, -1), [p.x, p.y]] });
      }
      return;
    }
    if (d.mode === "draw" && draft) {
      const a = d.start;
      switch (draft.kind) {
        case "rect": setDraft({ ...draft, x: Math.min(a.x, p.x), y: Math.min(a.y, p.y), w: Math.abs(p.x - a.x), h: Math.abs(p.y - a.y) }); break;
        case "ellipse": setDraft({ ...draft, cx: (a.x + p.x) / 2, cy: (a.y + p.y) / 2, rx: Math.abs(p.x - a.x) / 2, ry: Math.abs(p.y - a.y) / 2 }); break;
        case "line": case "arc": setDraft({ ...draft, x2: p.x, y2: p.y }); break;
        default: break;
      }
    } else if (d.mode === "move" && sel?.kind === "shape") {
      setShape(sel.i, moved(d.orig, p.x - d.start.x, p.y - d.start.y), true);
    } else if (d.mode === "handle" && sel?.kind === "shape") {
      setShape(sel.i, dragHandle(d.orig, d.h, p.x, p.y), true);
    } else if (d.mode === "pin" && sel?.kind === "pin") {
      setPin(sel.i, nearestEdge(p.x, p.y), true);
    }
  };

  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.mode === "draw" && draft) {
      const degenerate =
        (draft.kind === "rect" && (draft.w < 1 || draft.h < 1))
        || (draft.kind === "ellipse" && (draft.rx < 0.5 || draft.ry < 0.5))
        || ((draft.kind === "line" || draft.kind === "arc") && draft.x1 === draft.x2 && draft.y1 === draft.y2);
      if (!degenerate) {
        commit({ ...drawing, shapes: [...drawing.shapes, draft] });
        setSel({ kind: "shape", i: drawing.shapes.length });
      }
      setDraft(null);
      return;
    }
    // A move or handle drag changed `drawing` live; record the state before it once.
    if (before.current && before.current !== drawing) commit(drawing, before.current);
    before.current = null;
  };

  const startShapeDrag = (i: number) => (e: RPointerEvent) => {
    if (tool !== "select") return;
    e.stopPropagation();
    setSel({ kind: "shape", i });
    before.current = drawing;
    drag.current = { mode: "move", start: toBox(e), orig: drawing.shapes[i] };
  };
  const startHandleDrag = (i: number, h: string) => (e: RPointerEvent) => {
    e.stopPropagation();
    before.current = drawing;
    drag.current = { mode: "handle", h, orig: drawing.shapes[i] };
  };
  const startPinDrag = (i: number) => (e: RPointerEvent) => {
    e.stopPropagation();
    setSel({ kind: "pin", i });
    before.current = drawing;
    drag.current = { mode: "pin" };
  };

  const removeSelected = useCallback(() => {
    if (!sel) return;
    if (sel.kind === "shape") commit({ ...drawing, shapes: drawing.shapes.filter((_, j) => j !== sel.i) });
    else commit({ ...drawing, pins: drawing.pins.filter((_, j) => j !== sel.i) });
    setSel(null);
  }, [sel, drawing, commit]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select")) return;
      const mod = e.ctrlKey || e.metaKey;
      if (e.key === "Escape") {
        if (draft) setDraft(null);
        else if (sel) setSel(null);
        else onClose();
      } else if (e.key === "Enter") finishPolyline();
      else if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) step(redo, setUndo, setRedo); else step(undo, setRedo, setUndo);
      } else if ((e.key === "Delete" || e.key === "Backspace") && sel) {
        e.preventDefault();
        removeSelected();
      } else if (!mod && KEYS[e.key.toLowerCase()]) {
        setTool(KEYS[e.key.toLowerCase()]);
        setDraft(null);
      } else if (sel?.kind === "shape" && e.key.startsWith("Arrow")) {
        e.preventDefault();
        const n = snap ? 5 : 1;
        const [dx, dy] = { ArrowLeft: [-n, 0], ArrowRight: [n, 0], ArrowUp: [0, -n], ArrowDown: [0, n] }[e.key] ?? [0, 0];
        setShape(sel.i, moved(drawing.shapes[sel.i], dx, dy));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const save = async () => {
    if (!name.trim()) { setError("Give the icon a name."); return; }
    if (!drawing.shapes.length) { setError("Draw something first."); return; }
    setSaving(true);
    setError(null);
    const body = { name: name.trim(), svg: toSvg(drawing), tinted, ports: drawing.pins, source: drawing };
    try {
      onSaved(icon ? await api.patchIcon(icon.id, body) : await api.createIcon(body));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const selShape = sel?.kind === "shape" ? drawing.shapes[sel.i] : undefined;
  const selPin = sel?.kind === "pin" ? drawing.pins[sel.i] : undefined;
  const styleOf = selShape ?? style;
  const setStyleField = (patch: Partial<typeof style>) => {
    if (selShape && sel) setShape(sel.i, { ...selShape, ...patch } as Shape);
    setStyle((s) => ({ ...s, ...patch }));
  };
  const grid = [];
  for (let v = 0; v <= BOX; v += 10) {
    grid.push(<line key={"v" + v} x1={v} y1={0} x2={v} y2={BOX} className="ic-grid" />);
    grid.push(<line key={"h" + v} x1={0} y1={v} x2={BOX} y2={v} className="ic-grid" />);
  }

  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal icon-creator" role="dialog" aria-label="Icon creator">
        <header className="modal-head">
          <h2>{icon ? `Edit icon “${icon.name}”` : "New icon"}</h2>
          <span className="grow" />
          <button onClick={onClose} aria-label="Close">×</button>
        </header>
        {error && <p className="error">{error}</p>}
        <div className="ic-body">
          <div className="ic-tools" role="toolbar" aria-label="Drawing tools">
            {TOOLS.map(([t, glyph, title]) => (
              <button key={t} className={tool === t ? "on" : ""} title={title} aria-label={title} aria-pressed={tool === t}
                onClick={() => { setTool(t); setDraft(null); }}>{glyph}</button>
            ))}
            <span className="sep" />
            <button title="Undo (Ctrl+Z)" aria-label="Undo" disabled={!undo.length} onClick={() => step(undo, setRedo, setUndo)}>↶</button>
            <button title="Redo (Ctrl+Shift+Z)" aria-label="Redo" disabled={!redo.length} onClick={() => step(redo, setUndo, setRedo)}>↷</button>
          </div>
          <svg ref={svg} className={"ic-canvas tool-" + tool} viewBox={`${-PAD} ${-PAD} ${BOX + 2 * PAD} ${BOX + 2 * PAD}`}
            onPointerDown={onBackgroundDown} onPointerMove={onMove} onPointerUp={onUp}
            onDoubleClick={finishPolyline} aria-label="Icon drawing">
            <rect x={-PAD} y={-PAD} width={BOX + 2 * PAD} height={BOX + 2 * PAD} fill="transparent" />
            {snap && grid}
            <rect x={0} y={0} width={BOX} height={BOX} className="ic-box" />
            {drawing.shapes.map((s, i) => <ShapeEl key={i} s={s} />)}
            {draft && <ShapeEl s={draft} />}
            {tool === "select" && drawing.shapes.map((s, i) => <ShapeEl key={"hit" + i} s={s} hit onDown={startShapeDrag(i)} />)}
            {selShape && sel && handles(selShape).map(([h, x, y]) => (
              <rect key={h} x={x - 2} y={y - 2} width={4} height={4}
                className={"ic-handle" + (h === "bulge" ? " bulge" : "")} onPointerDown={startHandleDrag(sel.i, h)} />
            ))}
            {drawing.pins.map((p, i) => {
              const { x, y } = pinPoint(p);
              const lx = p.side === "left" ? x + 4 : p.side === "right" ? x - 4 : x;
              const ly = p.side === "top" ? y + 5 : p.side === "bottom" ? y - 5 : y;
              const anchor = p.side === "left" ? "start" : p.side === "right" ? "end" : "middle";
              return (
                <g key={"pin" + i}>
                  <rect x={x - 2.5} y={y - 2.5} width={5} height={5}
                    className={"ic-pin" + (sel?.kind === "pin" && sel.i === i ? " on" : "")} onPointerDown={startPinDrag(i)} />
                  <text x={lx} y={ly} className="ic-pin-label" textAnchor={anchor} dominantBaseline="middle">{p.label || p.id}</text>
                </g>
              );
            })}
          </svg>
          <div className="ic-props">
            {selPin ? (
              <>
                <h4>Pin</h4>
                <label>Id <input value={selPin.id} onChange={(e) => {
                  const v = e.target.value.trim().slice(0, 64);
                  if (v && !drawing.pins.some((p, j) => j !== sel!.i && p.id === v)) setPin(sel!.i, { id: v });
                }} /></label>
                <label>Label <input value={selPin.label ?? ""} onChange={(e) => setPin(sel!.i, { label: e.target.value.slice(0, 100) })} /></label>
                <label>Side <select value={selPin.side} onChange={(e) => setPin(sel!.i, { side: e.target.value as Side })}>
                  {SIDES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select></label>
                <label>Position <input type="range" min={0} max={1} step={0.05} value={selPin.at}
                  onChange={(e) => setPin(sel!.i, { at: Number(e.target.value) })} /></label>
                <button onClick={removeSelected}>Delete pin</button>
              </>
            ) : (
              <>
                <h4>{selShape ? selShape.kind : "New shapes"}</h4>
                {selShape?.kind !== "text" && (
                  <label>Stroke <input type="number" min={0.5} max={12} step={0.5} value={styleOf.sw}
                    onChange={(e) => setStyleField({ sw: Math.max(0.5, Math.min(12, Number(e.target.value) || 1)) })} /></label>
                )}
                {selShape?.kind !== "text" && selShape?.kind !== "line" && selShape?.kind !== "arc" && (
                  <label className="check"><input type="checkbox" checked={styleOf.fill}
                    onChange={(e) => setStyleField({ fill: e.target.checked })} /> Filled</label>
                )}
                <label>Colour <input type="color" value={styleOf.color} onChange={(e) => setStyleField({ color: e.target.value })} /></label>
                {selShape?.kind === "rect" && (
                  <label>Corner radius <input type="number" min={0} max={50} value={selShape.r}
                    onChange={(e) => setShape(sel!.i, { ...selShape, r: Math.max(0, Number(e.target.value) || 0) })} /></label>
                )}
                {selShape?.kind === "polyline" && (
                  <label className="check"><input type="checkbox" checked={selShape.closed}
                    onChange={(e) => setShape(sel!.i, { ...selShape, closed: e.target.checked })} /> Closed</label>
                )}
                {selShape?.kind === "arc" && (
                  <label>Bend <input type="range" min={-1} max={1} step={0.05} value={selShape.bulge}
                    onChange={(e) => setShape(sel!.i, { ...selShape, bulge: Number(e.target.value) })} /></label>
                )}
                {selShape?.kind === "text" && <>
                  <label>Text <input value={selShape.text} onChange={(e) => setShape(sel!.i, { ...selShape, text: e.target.value.slice(0, 40) })} /></label>
                  <label>Size <input type="number" min={4} max={80} value={selShape.size}
                    onChange={(e) => setShape(sel!.i, { ...selShape, size: Math.max(4, Math.min(80, Number(e.target.value) || 12)) })} /></label>
                </>}
                {selShape && <button onClick={removeSelected}>Delete shape</button>}
              </>
            )}
            <hr />
            <label className="check"><input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} /> Snap to grid</label>
            <p className="muted small">Pins sit on the box edge and become the icon's ports. Draw leads to the edge so lines meet them.</p>
          </div>
        </div>
        <footer className="ic-foot">
          <label>Name <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Resistor" /></label>
          <label className="check" title="Off keeps the colours you drew with">
            <input type="checkbox" checked={tinted} onChange={(e) => setTinted(e.target.checked)} /> Draw in the node's colour
          </label>
          <span className="grow" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={saving} onClick={() => void save()}>{saving ? "Saving…" : icon ? "Save" : "Create icon"}</button>
        </footer>
      </div>
    </div>
  );
}
