// One edge type for every edge: picks the path for its pathfindingMethod and
// steers around the other nodes on the canvas (routing.ts). Wires between
// schematic parts are routed together instead (wires.ts). An edge with
// waypoints (design §18) is drawn through them instead of routed.
import { createContext, memo, useCallback, useContext, useMemo, type PointerEvent as ReactPointerEvent } from "react";
import {
  BaseEdge, EdgeLabelRenderer, getBezierPath, getSmoothStepPath, getStraightPath, useReactFlow, useStore,
  type EdgeProps, type ReactFlowState,
} from "@xyflow/react";
import type { CEdge, CNode } from "./canvasMapping";
import {
  along, bezierAt, bezierHits, curveThrough, joinLegs, labelPoint, orthoLegs, orthoRoute, polyPath, waypointsOf,
  type Pt, type Rect, type Side,
} from "./routing";
import { attr, cornerRadius } from "./styles";
import { wireKey, wiresFor } from "./wires";

// A group's title sits above its box (.nw-group-label: 600 16px, 4px gap).
const TITLE_H = 26;
const TITLE_M = 4; // slim margin: nodes just inside the group stay reachable
const titleWidths = new Map<string, number>();
let measureCtx: CanvasRenderingContext2D | null | undefined;

function titleWidth(label: string): number {
  let w = titleWidths.get(label);
  if (w === undefined) {
    if (measureCtx === undefined) {
      measureCtx = document.createElement("canvas").getContext("2d");
      if (measureCtx) measureCtx.font = `600 16px ${getComputedStyle(document.body).fontFamily}`;
    }
    w = Math.ceil(measureCtx ? measureCtx.measureText(label).width : label.length * 9.5);
    titleWidths.set(label, w);
  }
  return w;
}

// Obstacles as a string so the selector result compares by value and the edge
// only re-renders when some other node actually moves or resizes. Groups
// aren't obstacles (edges go into them), but their titles are.
function obstacleKey(s: ReactFlowState, source: string, target: string): string {
  const parts: string[] = [];
  for (const n of s.nodeLookup.values()) {
    if (n.id === source || n.id === target || n.hidden) continue;
    const { x, y } = n.internals.positionAbsolute;
    if (n.type === "group") {
      const label = (n.data as CNode["data"])?.raw?.label;
      if (typeof label === "string" && label) {
        parts.push(`${Math.round(x)},${Math.round(y - TITLE_H)},${Math.round(x + titleWidth(label))},${Math.round(y)},${TITLE_M}`);
      }
      const w = n.width ?? n.measured?.width ?? 0, h = n.height ?? n.measured?.height ?? 0;
      parts.push(`${Math.round(x)},${Math.round(y)},${Math.round(x + w)},${Math.round(y + h)},F`);
      continue;
    }
    const w = n.width ?? n.measured?.width ?? 0, h = n.height ?? n.measured?.height ?? 0;
    parts.push(`${Math.round(x)},${Math.round(y)},${Math.round(x + w)},${Math.round(y + h)}`);
  }
  return parts.join(";");
}

/** Obstacles to route around, and frames (group boxes) a label shouldn't straddle. */
function parse(key: string): [Rect[], Rect[]] {
  const obstacles: Rect[] = [], frames: Rect[] = [];
  if (!key) return [obstacles, frames];
  for (const p of key.split(";")) {
    const f = p.split(",");
    const [x0, y0, x1, y1] = f.slice(0, 4).map(Number);
    if (f[4] === "F") frames.push({ x0, y0, x1, y1 });
    else if (f[4] !== undefined) obstacles.push({ x0, y0, x1, y1, m: Number(f[4]) });
    else obstacles.push({ x0, y0, x1, y1 });
  }
  return [obstacles, frames];
}

// React Flow draws edge labels at 10px; this is the box with its padding.
const labelBox = (label: unknown): [number, number] =>
  [String(label ?? "").length * 6 + 12, 18];

/** The document's colorByNet: wires take their net's colour unless given one (wires.ts). */
export const NetColours = createContext(false);

/** How the editor changes an edge's waypoints; null where lines can't be edited. */
export type WaypointEditor = {
  /** New waypoints for the edge, or [] to go back to automatic routing. */
  set: (edgeId: string, wps: Pt[]) => void;
  /** A point dropped by the user, snapped to the grid if snapping is on. */
  snap: (p: Pt) => Pt;
};
export const Waypoints = createContext<WaypointEditor | null>(null);

// A plain click on a "+" does nothing; dragging it this far adds the waypoint.
const DRAG_START = 3;

/** Handles on a selected line: one per waypoint (drag to move, double-click
 * to remove) and a "+" in the middle of each leg (drag to add one there). */
function WaypointHandles({ id, wps, mids, edit }: { id: string; wps: Pt[]; mids: Pt[]; edit: WaypointEditor }) {
  const flow = useReactFlow();
  const drag = (e: ReactPointerEvent, index: number, insert: boolean) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const at = (ev: { clientX: number; clientY: number }) =>
      edit.snap(flow.screenToFlowPosition({ x: ev.clientX, y: ev.clientY }));
    const x0 = e.clientX, y0 = e.clientY;
    let list: Pt[] | null = insert ? null : [...wps];
    const move = (ev: PointerEvent) => {
      const p = at(ev);
      if (!list) {
        if (Math.hypot(ev.clientX - x0, ev.clientY - y0) < DRAG_START) return;
        list = [...wps.slice(0, index), p, ...wps.slice(index)];
      } else if (list[index].x === p.x && list[index].y === p.y) {
        return;
      } else {
        list = list.map((q, i) => (i === index ? p : q));
      }
      edit.set(id, list);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const place = (p: Pt) => ({ transform: `translate(-50%, -50%) translate(${p.x}px, ${p.y}px)` });
  return (
    <EdgeLabelRenderer>
      {mids.map((p, i) => (
        <div key={`m${i}`} className="nw-wp-add nodrag nopan" style={place(p)}
          title="Drag to bend the line here" onPointerDown={(e) => drag(e, i, true)} />
      ))}
      {wps.map((p, i) => (
        <div key={`w${i}`} className="nw-wp nodrag nopan" style={place(p)}
          title="Drag to move · double-click to remove"
          onPointerDown={(e) => drag(e, i, false)}
          onDoubleClick={(e) => {
            e.stopPropagation();
            edit.set(id, wps.filter((_, j) => j !== i));
          }} />
      ))}
    </EdgeLabelRenderer>
  );
}

export const RoutedEdge = memo((p: EdgeProps<CEdge>) => {
  const byNet = useContext(NetColours);
  const edit = useContext(Waypoints);
  const raw = p.data?.raw;
  const wps = useMemo(() => waypointsOf(raw), [raw]);
  const method = attr(p.data?.raw ?? {}, "pathfindingMethod");
  const radius = cornerRadius(p.data?.raw ?? {});
  const select = useCallback((s: ReactFlowState) => obstacleKey(s, p.source, p.target),
    [p.source, p.target]);
  const key = useStore(select);
  const wires = useStore(wireKey);
  const wire = useMemo(() => wiresFor(wires).get(p.id), [wires, p.id]);
  const { sourceX: sx, sourceY: sy, targetX: tx, targetY: ty } = p;
  const sSide = p.sourcePosition as Side, tSide = p.targetPosition as Side;

  // The path, where its label goes, and the middle of each leg (for "+" handles).
  const [path, lx, ly, mids] = useMemo((): [string, number, number, Pt[]] => {
    if (wire) return [wire.d, wire.label.x, wire.label.y, wire.mids];
    const base = { sourceX: sx, sourceY: sy, targetX: tx, targetY: ty,
      sourcePosition: p.sourcePosition, targetPosition: p.targetPosition };
    const s = { x: sx, y: sy }, t = { x: tx, y: ty };
    // With a label in the middle, a lone "+" goes a quarter of the way along instead.
    const u = p.label ? 0.25 : 0.5;
    const orthogonal = method === "square" || method === "a-star";
    if (wps.length) {
      const [obstacles, frames] = parse(key);
      const place = (pts: Pt[]) => (p.label ? labelPoint(pts, ...labelBox(p.label), obstacles, frames) : along(pts, 0.5));
      if (orthogonal || method === "direct") {
        const legs = orthogonal ? orthoLegs(s, sSide, wps, t, tSide)
          : [s, ...wps].map((a, i) => [a, [...wps, t][i]]);
        const { pts, mids: m } = joinLegs(legs);
        const at = place(pts);
        return [polyPath(pts, orthogonal ? radius ?? (method === "square" ? 0 : 12) : 0), at.x, at.y, m];
      }
      const ctl = [s, ...wps, t];
      const at = place(ctl);
      return [curveThrough(s, sSide, wps, t, tSide), at.x, at.y, ctl.slice(1).map((b, i) => along([ctl[i], b], 0.5))];
    }
    if (method === "direct") {
      const [d, x, y] = getStraightPath(base);
      return [d, x, y, [along([s, t], u)]];
    }
    const [obstacles, frames] = parse(key);
    if (orthogonal || bezierHits(s, sSide, t, tSide, obstacles)) {
      const pts = orthoRoute(s, sSide, t, tSide, obstacles);
      if (pts) {
        const m = p.label ? labelPoint(pts, ...labelBox(p.label), obstacles, frames) : along(pts, 0.5);
        return [polyPath(pts, radius ?? (method === "square" ? 0 : 12)), m.x, m.y, [along(pts, u)]];
      }
    }
    if (orthogonal) {
      const [d, x, y] = getSmoothStepPath({ ...base, borderRadius: radius ?? (method === "square" ? 0 : 8) });
      return [d, x, y, [{ x, y }]];
    }
    const [d, x, y] = getBezierPath(base);
    return [d, x, y, [bezierAt(s, sSide, t, tSide, u)]];
  }, [wire, wps, method, radius, key, sx, sy, tx, ty, sSide, tSide, p.sourcePosition, p.targetPosition, p.label]);

  const width = Number(p.style?.strokeWidth) || 2;
  const style = wire && byNet && !p.data?.raw?.color ? { ...p.style, stroke: wire.color } : p.style;
  return (
    <>
    {p.selected && <path d={path} className="nw-edge-halo" style={{ strokeWidth: width + 12 }} />}
    {p.data?.dangling && (
      <path d={path} className="nw-edge-dangling" style={{ strokeWidth: width + 8 }}>
        <title>This line names a port its node no longer has; it's drawn from the side instead.</title>
      </path>
    )}
    <BaseEdge
      id={p.id}
      path={path}
      labelX={lx}
      labelY={ly}
      label={p.label}
      labelStyle={p.labelStyle}
      labelShowBg
      labelBgStyle={p.labelBgStyle}
      labelBgPadding={[6, 3]}
      labelBgBorderRadius={4}
      markerStart={p.markerStart}
      markerEnd={p.markerEnd}
      style={style}
      interactionWidth={p.interactionWidth}
    />
    {wire?.dots.map((d) => (
      <circle key={`${d.x},${d.y}`} className="nw-wire-dot" cx={d.x} cy={d.y} r={width + 1.5}
        style={{ fill: style?.stroke }} />
    ))}
    {p.selected && edit && <WaypointHandles id={p.id} wps={wps} mids={mids} edit={edit} />}
    </>
  );
});
