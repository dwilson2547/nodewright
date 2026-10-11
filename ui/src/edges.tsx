// One edge type for every edge: picks the path for its pathfindingMethod and
// steers around the other nodes on the canvas (routing.ts).
import { memo, useCallback, useMemo } from "react";
import {
  BaseEdge, getBezierPath, getSmoothStepPath, getStraightPath, useStore,
  type EdgeProps, type ReactFlowState,
} from "@xyflow/react";
import type { CEdge } from "./canvasMapping";
import { bezierHits, midpoint, orthoRoute, polyPath, type Rect, type Side } from "./routing";
import { attr } from "./styles";

// Obstacles as a string so the selector result compares by value and the edge
// only re-renders when some other node actually moves or resizes.
function obstacleKey(s: ReactFlowState, source: string, target: string): string {
  const parts: string[] = [];
  for (const n of s.nodeLookup.values()) {
    if (n.id === source || n.id === target || n.type === "group" || n.hidden) continue;
    const { x, y } = n.internals.positionAbsolute;
    const w = n.width ?? n.measured?.width ?? 0, h = n.height ?? n.measured?.height ?? 0;
    parts.push(`${Math.round(x)},${Math.round(y)},${Math.round(x + w)},${Math.round(y + h)}`);
  }
  return parts.join(";");
}

function parse(key: string): Rect[] {
  if (!key) return [];
  return key.split(";").map((p) => {
    const [x0, y0, x1, y1] = p.split(",").map(Number);
    return { x0, y0, x1, y1 };
  });
}

export const RoutedEdge = memo((p: EdgeProps<CEdge>) => {
  const method = attr(p.data?.raw ?? {}, "pathfindingMethod");
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
    const obstacles = parse(key);
    const s = { x: sx, y: sy }, t = { x: tx, y: ty };
    const orthogonal = method === "square" || method === "a-star";
    if (orthogonal || bezierHits(s, sSide, t, tSide, obstacles)) {
      const pts = orthoRoute(s, sSide, t, tSide, obstacles);
      if (pts) {
        const m = midpoint(pts);
        return [polyPath(pts, method === "square" ? 0 : 12), m.x, m.y];
      }
    }
    if (orthogonal) {
      const [d, x, y] = getSmoothStepPath({ ...base, borderRadius: method === "square" ? 0 : 8 });
      return [d, x, y];
    }
    const [d, x, y] = getBezierPath(base);
    return [d, x, y];
  }, [method, key, sx, sy, tx, ty, sSide, tSide, p.sourcePosition, p.targetPosition]);

  return (
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
  );
});
