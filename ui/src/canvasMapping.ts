// JSON Canvas <-> React Flow. Each React Flow node/edge carries the original
// JSON Canvas object in data.raw, so keys this editor doesn't understand
// (style extensions, other tools' fields) survive every save.
import type { Edge, Node } from "@xyflow/react";
import type { JsonCanvas } from "./api";
import { attr, dashArray, lineWidth } from "./styles";

export type Side = "top" | "right" | "bottom" | "left";
export type CanvasNodeData = { raw: Record<string, any> };
export type CanvasEdgeData = { raw: Record<string, any> };
export type CNode = Node<CanvasNodeData>;
export type CEdge = Edge<CanvasEdgeData>;

// Preset colours are deliberately undefined by the spec; these follow Obsidian's.
export const PRESETS: Record<string, string> = {
  "1": "#e93147",
  "2": "#ec7500",
  "3": "#e0ac00",
  "4": "#08b94e",
  "5": "#00bfbc",
  "6": "#7852ee",
};
export const DEFAULT_COLOR = "#8a8f98";

export function resolveColor(c: unknown): string | undefined {
  if (typeof c !== "string" || !c) return undefined;
  if (PRESETS[c]) return PRESETS[c];
  return /^#[0-9a-fA-F]{3,8}$/.test(c) ? c : undefined;
}

export function newId(): string {
  const b = new Uint8Array(8);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

function center(n: Record<string, any>) {
  return { x: n.x + n.width / 2, y: n.y + n.height / 2 };
}

// Obsidian picks the facing sides when an edge doesn't name them; so do we,
// for display only. The raw edge keeps no side until the user sets one.
function facingSides(a: Record<string, any>, b: Record<string, any>): [Side, Side] {
  const ca = center(a), cb = center(b);
  const dx = cb.x - ca.x, dy = cb.y - ca.y;
  if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? ["right", "left"] : ["left", "right"];
  return dy > 0 ? ["bottom", "top"] : ["top", "bottom"];
}

// Edge routing (styleAttributes.pathfindingMethod) -> React Flow edge type.
// Advanced Canvas's "a-star" routes around nodes; we draw rounded right
// angles, which is the same shape without the obstacle avoidance.
const ROUTES: Record<string, string> = { direct: "straight", square: "step", "a-star": "smoothstep" };

/** Id of the <marker> drawing this arrow shape in this colour (see Markers). */
export function markerId(arrow: string, color: string): string {
  return `nwm-${arrow || "triangle"}-${color.replace(/[^0-9a-zA-Z]/g, "")}`;
}

export function edgeVisual(raw: Record<string, any>) {
  const color = resolveColor(raw.color) ?? DEFAULT_COLOR;
  const width = lineWidth(raw);
  const path = attr(raw, "path");
  const marker = markerId(attr(raw, "arrow"), color);
  return {
    type: ROUTES[attr(raw, "pathfindingMethod")] ?? "default",
    label: raw.label || undefined,
    style: {
      stroke: color,
      strokeWidth: width,
      strokeDasharray: dashArray(path, width),
      strokeLinecap: path === "dotted" ? ("round" as const) : undefined,
    },
    markerEnd: (raw.toEnd ?? "arrow") === "arrow" ? marker : undefined,
    markerStart: raw.fromEnd === "arrow" ? marker : undefined,
    labelBgStyle: { fill: "var(--bg)" },
    labelStyle: { fill: "var(--fg)" },
  };
}

export function toFlow(doc: JsonCanvas): { nodes: CNode[]; edges: CEdge[] } {
  const rawNodes = Array.isArray(doc.nodes) ? doc.nodes : [];
  const byId = new Map(rawNodes.map((n: any) => [n.id, n]));
  const nodes: CNode[] = rawNodes.map((n: any) => ({
    id: n.id,
    type: n.type,
    position: { x: n.x, y: n.y },
    width: n.width,
    height: n.height,
    // Groups sit under everything else; within each layer the array order
    // (the spec's z-order) is kept.
    zIndex: n.type === "group" ? 0 : 1,
    data: { raw: n },
  }));
  const edges: CEdge[] = (Array.isArray(doc.edges) ? doc.edges : []).map((e: any) => {
    const from = byId.get(e.fromNode), to = byId.get(e.toNode);
    const [fs, ts] = from && to ? facingSides(from, to) : ["right", "left"];
    return {
      id: e.id,
      source: e.fromNode,
      target: e.toNode,
      sourceHandle: e.fromSide ?? fs,
      targetHandle: e.toSide ?? ts,
      data: { raw: e },
      ...edgeVisual(e),
    };
  });
  return { nodes, edges };
}

export function toCanvas(nodes: CNode[], edges: CEdge[], extra: Record<string, unknown> = {}): JsonCanvas {
  return {
    ...extra,
    nodes: nodes.map((n) => ({
      ...n.data.raw,
      id: n.id,
      x: Math.round(n.position.x),
      y: Math.round(n.position.y),
      width: Math.round(n.width ?? n.measured?.width ?? n.data.raw.width),
      height: Math.round(n.height ?? n.measured?.height ?? n.data.raw.height),
    })),
    edges: edges.map((e) => ({ ...e.data!.raw, id: e.id, fromNode: e.source, toNode: e.target })),
  };
}
