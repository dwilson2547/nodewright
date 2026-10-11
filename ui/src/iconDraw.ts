// The icon creator's drawing (design §13.2): shapes and pins in a 100x100
// box. Saved with the icon as `source` so it can be reopened; toSvg() makes
// the SVG the server validates and shows, and pins become the icon's ports.
import type { Port } from "./ports";

export const BOX = 100;

type Style = { sw: number; fill: boolean; color: string };
export type Shape = Style & (
  | { kind: "rect"; x: number; y: number; w: number; h: number; r: number }
  | { kind: "ellipse"; cx: number; cy: number; rx: number; ry: number }
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number }
  | { kind: "polyline"; points: [number, number][]; closed: boolean }
  // A circular arc over the chord (x1,y1)-(x2,y2); bulge -1..1 is the
  // sagitta as a fraction of half the chord (±1 = semicircle, 0 = straight).
  | { kind: "arc"; x1: number; y1: number; x2: number; y2: number; bulge: number }
  | { kind: "text"; x: number; y: number; text: string; size: number }
);
export type Kind = Shape["kind"];
export type Drawing = { version: 1; shapes: Shape[]; pins: Port[] };

export const DEFAULT_STYLE: Style = { sw: 4, fill: false, color: "#000000" };
export const empty = (): Drawing => ({ version: 1, shapes: [], pins: [] });

const r2 = (n: number) => Math.round(n * 100) / 100;

/** The point at the middle of an arc, and the SVG path for it. */
export function arcGeometry(s: { x1: number; y1: number; x2: number; y2: number; bulge: number }) {
  const dx = s.x2 - s.x1, dy = s.y2 - s.y1;
  const c = Math.hypot(dx, dy);
  const mx = (s.x1 + s.x2) / 2, my = (s.y1 + s.y2) / 2;
  if (c === 0) return { d: `M ${r2(s.x1)} ${r2(s.y1)}`, mid: { x: mx, y: my }, normal: { x: 0, y: -1 }, half: 0 };
  // Left-hand normal of the chord; positive bulge bows that way.
  const nx = dy / c, ny = -dx / c;
  const sag = s.bulge * (c / 2);
  const mid = { x: mx + nx * sag, y: my + ny * sag };
  if (Math.abs(sag) < 0.01) {
    return { d: `M ${r2(s.x1)} ${r2(s.y1)} L ${r2(s.x2)} ${r2(s.y2)}`, mid, normal: { x: nx, y: ny }, half: c / 2 };
  }
  const radius = (c * c / 4 + sag * sag) / (2 * Math.abs(sag));
  const sweep = sag > 0 ? 1 : 0;
  return {
    d: `M ${r2(s.x1)} ${r2(s.y1)} A ${r2(radius)} ${r2(radius)} 0 0 ${sweep} ${r2(s.x2)} ${r2(s.y2)}`,
    mid, normal: { x: nx, y: ny }, half: c / 2,
  };
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** One shape as SVG markup (also used to draw it in the creator). */
export function shapeSvg(s: Shape): string {
  const paint = `stroke="${esc(s.color)}" stroke-width="${s.sw}" fill="${s.fill ? esc(s.color) : "none"}"`;
  switch (s.kind) {
    case "rect":
      return `<rect x="${r2(s.x)}" y="${r2(s.y)}" width="${r2(s.w)}" height="${r2(s.h)}" rx="${r2(s.r)}" ${paint}/>`;
    case "ellipse":
      return `<ellipse cx="${r2(s.cx)}" cy="${r2(s.cy)}" rx="${r2(s.rx)}" ry="${r2(s.ry)}" ${paint}/>`;
    case "line":
      return `<line x1="${r2(s.x1)}" y1="${r2(s.y1)}" x2="${r2(s.x2)}" y2="${r2(s.y2)}" ${paint}/>`;
    case "polyline": {
      const pts = s.points.map(([x, y]) => `${r2(x)},${r2(y)}`).join(" ");
      return `<${s.closed ? "polygon" : "polyline"} points="${pts}" ${paint}/>`;
    }
    case "arc":
      return `<path d="${arcGeometry(s).d}" ${paint}/>`;
    case "text":
      return `<text x="${r2(s.x)}" y="${r2(s.y)}" font-size="${s.size}" font-family="sans-serif" `
        + `text-anchor="middle" dominant-baseline="middle" fill="${esc(s.color)}">${esc(s.text)}</text>`;
  }
}

export function toSvg(d: Drawing): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${BOX} ${BOX}" `
    + `stroke-linecap="round" stroke-linejoin="round">${d.shapes.map(shapeSvg).join("")}</svg>`;
}

/** Where a pin sits in box coordinates. */
export function pinPoint(p: Port): { x: number; y: number } {
  if (p.side === "left") return { x: 0, y: p.at * BOX };
  if (p.side === "right") return { x: BOX, y: p.at * BOX };
  if (p.side === "top") return { x: p.at * BOX, y: 0 };
  return { x: p.at * BOX, y: BOX };
}

/** The pin position on the box edge nearest (x, y). */
export function nearestEdge(x: number, y: number): Pick<Port, "side" | "at"> {
  const cx = Math.min(BOX, Math.max(0, x)), cy = Math.min(BOX, Math.max(0, y));
  const d = { left: cx, right: BOX - cx, top: cy, bottom: BOX - cy };
  const side = (Object.keys(d) as Port["side"][]).reduce((a, b) => (d[b] < d[a] ? b : a));
  const at = side === "left" || side === "right" ? cy / BOX : cx / BOX;
  return { side, at: Math.round(at * 1000) / 1000 };
}

/** The shape moved by (dx, dy). */
export function moved(s: Shape, dx: number, dy: number): Shape {
  switch (s.kind) {
    case "rect": return { ...s, x: s.x + dx, y: s.y + dy };
    case "ellipse": return { ...s, cx: s.cx + dx, cy: s.cy + dy };
    case "line": case "arc": return { ...s, x1: s.x1 + dx, y1: s.y1 + dy, x2: s.x2 + dx, y2: s.y2 + dy };
    case "polyline": return { ...s, points: s.points.map(([x, y]) => [x + dx, y + dy] as [number, number]) };
    case "text": return { ...s, x: s.x + dx, y: s.y + dy };
  }
}

/** Draggable points of a shape: [id, x, y]. */
export function handles(s: Shape): [string, number, number][] {
  switch (s.kind) {
    case "rect": return [["tl", s.x, s.y], ["tr", s.x + s.w, s.y], ["bl", s.x, s.y + s.h], ["br", s.x + s.w, s.y + s.h]];
    case "ellipse": return [["tl", s.cx - s.rx, s.cy - s.ry], ["br", s.cx + s.rx, s.cy + s.ry]];
    case "line": return [["a", s.x1, s.y1], ["b", s.x2, s.y2]];
    case "arc": {
      const m = arcGeometry(s).mid;
      return [["a", s.x1, s.y1], ["b", s.x2, s.y2], ["bulge", m.x, m.y]];
    }
    case "polyline": return s.points.map(([x, y], i) => [String(i), x, y]);
    case "text": return [];
  }
}

/** The shape with handle `h` dragged to (x, y). */
export function dragHandle(s: Shape, h: string, x: number, y: number): Shape {
  switch (s.kind) {
    case "rect": {
      const x0 = h.includes("l") ? x : s.x, x1 = h.includes("r") ? x : s.x + s.w;
      const y0 = h.includes("t") ? y : s.y, y1 = h.includes("b") ? y : s.y + s.h;
      return { ...s, x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
    }
    case "ellipse": {
      const [ox, oy] = h === "tl" ? [s.cx + s.rx, s.cy + s.ry] : [s.cx - s.rx, s.cy - s.ry];
      return { ...s, cx: (ox + x) / 2, cy: (oy + y) / 2, rx: Math.abs(x - ox) / 2, ry: Math.abs(y - oy) / 2 };
    }
    case "line": return h === "a" ? { ...s, x1: x, y1: y } : { ...s, x2: x, y2: y };
    case "arc": {
      if (h === "a") return { ...s, x1: x, y1: y };
      if (h === "b") return { ...s, x2: x, y2: y };
      const g = arcGeometry(s);
      if (g.half === 0) return s;
      const mx = (s.x1 + s.x2) / 2, my = (s.y1 + s.y2) / 2;
      const sag = (x - mx) * g.normal.x + (y - my) * g.normal.y;
      return { ...s, bulge: Math.max(-1, Math.min(1, Math.round((sag / g.half) * 100) / 100)) };
    }
    case "polyline": {
      const i = Number(h);
      return { ...s, points: s.points.map((p, j) => (j === i ? [x, y] : p) as [number, number]) };
    }
    case "text": return s;
  }
}
