// One edge type for every edge: picks the path for its pathfindingMethod and
// steers around the other nodes on the canvas (routing.ts).
import { memo, useCallback, useMemo } from "react";
import {
  BaseEdge, getBezierPath, getSmoothStepPath, getStraightPath, useStore,
  type EdgeProps, type ReactFlowState,
} from "@xyflow/react";
import type { CEdge, CNode } from "./canvasMapping";
import { bezierHits, labelPoint, midpoint, orthoRoute, polyPath, type Rect, type Side } from "./routing";
import { attr, cornerRadius } from "./styles";

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

export const RoutedEdge = memo((p: EdgeProps<CEdge>) => {
  const method = attr(p.data?.raw ?? {}, "pathfindingMethod");
  const radius = cornerRadius(p.data?.raw ?? {});
  const select = useCallback((s: ReactFlowState) => obstacleKey(s, p.source, p.target),
    [p.source, p.target]);
  const key = useStore(select);
  const { sourceX: sx, sourceY: sy, targetX: tx, targetY: ty } = p;
  const sSide = p.sourcePosition as Side, tSide = p.targetPosition as Side;

  const [path, lx, ly] = useMemo((): [string, number, number] => {
    const base = { sourceX: sx, sourceY: sy, targetX: tx, targetY: ty,
      sourcePosition: p.sourcePosition, targetPosition: p.targetPosition };
    if (method === "direct") {
      const [d, x, y] = getStraightPath(base);
      return [d, x, y];
    }
    const [obstacles, frames] = parse(key);
    const s = { x: sx, y: sy }, t = { x: tx, y: ty };
    const orthogonal = method === "square" || method === "a-star";
    if (orthogonal || bezierHits(s, sSide, t, tSide, obstacles)) {
      const pts = orthoRoute(s, sSide, t, tSide, obstacles);
      if (pts) {
        const m = p.label ? labelPoint(pts, ...labelBox(p.label), obstacles, frames) : midpoint(pts);
        return [polyPath(pts, radius ?? (method === "square" ? 0 : 12)), m.x, m.y];
      }
    }
    if (orthogonal) {
      const [d, x, y] = getSmoothStepPath({ ...base, borderRadius: radius ?? (method === "square" ? 0 : 8) });
      return [d, x, y];
    }
    const [d, x, y] = getBezierPath(base);
    return [d, x, y];
  }, [method, radius, key, sx, sy, tx, ty, sSide, tSide, p.sourcePosition, p.targetPosition, p.label]);

  const width = Number(p.style?.strokeWidth) || 2;
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
      style={p.style}
      interactionWidth={p.interactionWidth}
    />
    </>
  );
});
