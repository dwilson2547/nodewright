// Edge routing around nodes. JSON Canvas edges carry no waypoints, so routes
// are computed whenever an edge is drawn: an orthogonal A* over a sparse grid
// whose lines run MARGIN outside every obstacle (Wybrow-style connector
// routing), with a penalty per bend so routes stay simple.

export type Pt = { x: number; y: number };
/** `m` overrides MARGIN: how far routes keep clear of this obstacle. */
export type Rect = { x0: number; y0: number; x1: number; y1: number; m?: number };
export type Side = "top" | "right" | "bottom" | "left";

export const MARGIN = 20;
const BEND = 60;
const REACH = 400; // obstacles further than this outside the endpoints' box are ignored
const DIRS: Pt[] = [{ x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }, { x: 0, y: -1 }];
const SIDE_DIR: Record<Side, number> = { right: 0, bottom: 1, left: 2, top: 3 };

function blocks(r: Rect, a: Pt, b: Pt): boolean {
  // Does the axis-aligned segment a-b enter r's interior?
  const lx = Math.min(a.x, b.x), hx = Math.max(a.x, b.x);
  const ly = Math.min(a.y, b.y), hy = Math.max(a.y, b.y);
  return lx < r.x1 && hx > r.x0 && ly < r.y1 && hy > r.y0;
}

class Heap {
  private a: [number, number][] = [];
  get size() { return this.a.length; }
  push(k: number, v: number) {
    const a = this.a;
    a.push([k, v]);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p][0] <= a[i][0]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop(): number {
    const a = this.a, top = a[0][1], last = a.pop()!;
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }
}

/** Orthogonal route from s (leaving through sSide) to t (entering through
 * tSide) that keeps MARGIN clear of every obstacle, or null if boxed in. */
export function orthoRoute(s: Pt, sSide: Side, t: Pt, tSide: Side, obstacles: Rect[]): Pt[] | null {
  const sd = SIDE_DIR[sSide], td = SIDE_DIR[tSide];
  const s1 = { x: s.x + DIRS[sd].x * MARGIN, y: s.y + DIRS[sd].y * MARGIN };
  const t1 = { x: t.x + DIRS[td].x * MARGIN, y: t.y + DIRS[td].y * MARGIN };
  const bx0 = Math.min(s1.x, t1.x) - REACH, bx1 = Math.max(s1.x, t1.x) + REACH;
  const by0 = Math.min(s1.y, t1.y) - REACH, by1 = Math.max(s1.y, t1.y) + REACH;
  const near = obstacles.filter((r) => r.x1 > bx0 && r.x0 < bx1 && r.y1 > by0 && r.y0 < by1);
  // Blocked zones stop 1px short of the grid lines, so the lines themselves are free.
  const zones = near.map((r) => {
    const m = r.m ?? MARGIN;
    return { x0: r.x0 - m + 1, y0: r.y0 - m + 1, x1: r.x1 + m - 1, y1: r.y1 + m - 1 };
  });

  const xs = new Set([s1.x, t1.x, (s1.x + t1.x) / 2]);
  const ys = new Set([s1.y, t1.y, (s1.y + t1.y) / 2]);
  for (const r of near) {
    const m = r.m ?? MARGIN;
    xs.add(r.x0 - m); xs.add(r.x1 + m);
    ys.add(r.y0 - m); ys.add(r.y1 + m);
  }
  const X = [...xs].sort((a, b) => a - b), Y = [...ys].sort((a, b) => a - b);
  const nx = X.length, ny = Y.length;
  const at = (i: number, j: number): Pt => ({ x: X[i], y: Y[j] });
  const free = (p: Pt) => !zones.some((z) => p.x > z.x0 && p.x < z.x1 && p.y > z.y0 && p.y < z.y1);
  const si = X.indexOf(s1.x), sj = Y.indexOf(s1.y);
  const ti = X.indexOf(t1.x), tj = Y.indexOf(t1.y);
  const arrive = (td + 2) % 4; // direction of travel into the target

  // State = (i, j, direction of travel); key packs all three.
  const key = (i: number, j: number, d: number) => (i * ny + j) * 4 + d;
  const g = new Map<number, number>();
  const prev = new Map<number, number>();
  const h = (i: number, j: number) => Math.abs(X[i] - t1.x) + Math.abs(Y[j] - t1.y);
  const open = new Heap();
  const start = key(si, sj, sd);
  g.set(start, 0);
  open.push(h(si, sj), start);
  let goal = -1;
  let budget = 20000;
  while (open.size && budget-- > 0) {
    const k = open.pop();
    const d = k % 4, ij = (k - d) / 4, j = ij % ny, i = (ij - j) / ny;
    const gk = g.get(k)!;
    if (i === ti && j === tj) { goal = k; break; }
    for (let nd = 0; nd < 4; nd++) {
      if (nd === (d + 2) % 4) continue;
      const ni = i + DIRS[nd].x, nj = j + DIRS[nd].y;
      if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
      const a = at(i, j), b = at(ni, nj);
      const isGoal = ni === ti && nj === tj;
      if (!isGoal && !free(b)) continue;
      if (zones.some((z) => blocks(z, a, b))) continue;
      let cost = gk + Math.abs(b.x - a.x) + Math.abs(b.y - a.y) + (nd === d ? 0 : BEND);
      if (isGoal && nd !== arrive) cost += BEND;
      const nk = key(ni, nj, nd);
      if (cost < (g.get(nk) ?? Infinity)) {
        g.set(nk, cost);
        prev.set(nk, k);
        open.push(cost + h(ni, nj), nk);
      }
    }
  }
  if (goal < 0) return null;
  const pts: Pt[] = [t];
  for (let k: number | undefined = goal; k !== undefined; k = prev.get(k)) {
    const d = k % 4, ij = (k - d) / 4, j = ij % ny;
    pts.push(at((ij - j) / ny, j));
  }
  pts.push(s);
  pts.reverse();
  return simplify(pts);
}

function simplify(pts: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (const p of pts) {
    if (out.length && out[out.length - 1].x === p.x && out[out.length - 1].y === p.y) continue;
    if (out.length >= 2) {
      const a = out[out.length - 2], b = out[out.length - 1];
      if ((a.x === b.x && b.x === p.x) || (a.y === b.y && b.y === p.y)) out.pop();
    }
    out.push(p);
  }
  return out;
}

/** SVG path through `pts`, corners rounded to `radius`. */
export function polyPath(pts: Pt[], radius: number): string {
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i - 1], b = pts[i], c = pts[i + 1];
    const r = Math.min(radius, Math.hypot(b.x - a.x, b.y - a.y) / 2, Math.hypot(c.x - b.x, c.y - b.y) / 2);
    if (r <= 0) { d += ` L ${b.x} ${b.y}`; continue; }
    const ux = Math.sign(b.x - a.x), uy = Math.sign(b.y - a.y);
    const vx = Math.sign(c.x - b.x), vy = Math.sign(c.y - b.y);
    d += ` L ${b.x - ux * r} ${b.y - uy * r} Q ${b.x} ${b.y} ${b.x + vx * r} ${b.y + vy * r}`;
  }
  const z = pts[pts.length - 1];
  return d + ` L ${z.x} ${z.y}`;
}

/** Point `frac` of the way along the polyline. */
export function along(pts: Pt[], frac: number): Pt {
  const lens = pts.slice(1).map((p, i) => Math.hypot(p.x - pts[i].x, p.y - pts[i].y));
  let rest = lens.reduce((a, b) => a + b, 0) * frac;
  for (let i = 0; i < lens.length; i++) {
    if (rest <= lens[i] && lens[i] > 0) {
      const f = rest / lens[i];
      return { x: pts[i].x + (pts[i + 1].x - pts[i].x) * f, y: pts[i].y + (pts[i + 1].y - pts[i].y) * f };
    }
    rest -= lens[i];
  }
  return pts[pts.length - 1];
}

export function midpoint(pts: Pt[]): Pt {
  return along(pts, 0.5);
}

const overlaps = (a: Rect, b: Rect) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
const straddles = (a: Rect, f: Rect) => overlaps(a, f) &&
  !(a.x0 >= f.x0 && a.x1 <= f.x1 && a.y0 >= f.y0 && a.y1 <= f.y1);

/** Where along the route to put a w x h label: the point nearest the middle
 * whose label box clears every obstacle and doesn't straddle a frame (a
 * group's border); the middle if nowhere does. */
export function labelPoint(pts: Pt[], w: number, h: number, obstacles: Rect[], frames: Rect[]): Pt {
  for (const off of [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35]) {
    for (const frac of off ? [0.5 - off, 0.5 + off] : [0.5]) {
      const p = along(pts, frac);
      const box = { x0: p.x - w / 2, y0: p.y - h / 2, x1: p.x + w / 2, y1: p.y + h / 2 };
      if (!obstacles.some((r) => overlaps(box, r)) && !frames.some((f) => straddles(box, f))) return p;
    }
  }
  return along(pts, 0.5);
}

// React Flow's default bezier (getBezierPath, curvature 0.25), so we can tell
// whether the curve it would draw passes through a node.
function offset(distance: number): number {
  return distance >= 0 ? 0.5 * distance : 0.25 * 25 * Math.sqrt(-distance);
}

function control(side: Side, a: Pt, b: Pt): Pt {
  switch (side) {
    case "left": return { x: a.x - offset(a.x - b.x), y: a.y };
    case "right": return { x: a.x + offset(b.x - a.x), y: a.y };
    case "top": return { x: a.x, y: a.y - offset(a.y - b.y) };
    default: return { x: a.x, y: a.y + offset(b.y - a.y) };
  }
}

export function bezierHits(s: Pt, sSide: Side, t: Pt, tSide: Side, obstacles: Rect[]): boolean {
  if (!obstacles.length) return false;
  const c1 = control(sSide, s, t), c2 = control(tSide, t, s);
  for (let k = 1; k < 32; k++) {
    const u = k / 32, v = 1 - u;
    const x = v * v * v * s.x + 3 * v * v * u * c1.x + 3 * v * u * u * c2.x + u * u * u * t.x;
    const y = v * v * v * s.y + 3 * v * v * u * c1.y + 3 * v * u * u * c2.y + u * u * u * t.y;
    if (obstacles.some((r) => x > r.x0 && x < r.x1 && y > r.y0 && y < r.y1)) return true;
  }
  return false;
}
