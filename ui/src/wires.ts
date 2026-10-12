// Schematic wires (design §16): lines that run pin to pin between schematic
// parts (symbols, junctions, net labels). They are routed together rather than
// one at a time, so each sees the others: right angles only, clear of every
// part including their own, a cost for crossing another net's wire and no
// running along one. Where wires of different nets cross, the horizontal one
// hops; where wires leaving one pin split, a dot marks the join. Nothing here
// is saved: it's worked out from the document whenever it's drawn.
import type { ReactFlowState } from "@xyflow/react";
import { portFromHandle, portsOf, type Port } from "./ports";
import { DIRS, Heap, labelPoint, SIDE_DIR, simplify, type Pt, type Rect, type Side } from "./routing";
import { attr } from "./styles";
import { captionSide } from "./nodes";

export const WIRE_MARGIN = 10;
const CROSS = 100; // a crossing costs about as much as 100px of detour
const OVERLAP = 2000; // running along another net's wire would look like a connection
const BEND = 60;
const REACH = 200; // parts further than this outside the two pins' box are ignored
const BUDGET = 20000;

type Seg = { a: Pt; b: Pt };
const HOP = 5;
const JUNCTION = /^icons\/sym-junction\//;

type Box = { x: number; y: number; w: number; h: number };
type WNode = Box & {
  id: string; kind: "symbol" | "junction" | "net" | "group" | "other"; net?: string; ports: Port[];
  /** A symbol's caption box (nodes.tsx captionSide), which wires keep clear of too. */
  caption?: Box;
  /** Being dragged: only the wires on it are re-routed until it's dropped. */
  drag?: true;
  /** A ground symbol: its net is "gnd". */
  ground?: true;
};
type WEdge = { id: string; source: string; target: string; sp: string | null; tp: string | null; label?: string };
type Input = { nodes: WNode[]; edges: WEdge[] };

export type Wire = { d: string; label: Pt; dots: Pt[]; /** The net's colour, for colour by net. */ color: string };

// Colour by net (design §17): each net gets a colour from its name, so it
// stays put as parts move. Ground stays the default grey.
const NET_COLOURS = ["#e5484d", "#f76b15", "#c99a06", "#30a46c", "#12a594", "#0091ff", "#3e63dd", "#8e4ec6", "#d6409f", "#a0715a"];
const GROUND = "#8a8f98";

function preferred(name: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < name.length; i++) h = Math.imul(h ^ name.charCodeAt(i), 0x01000193);
  return (h >>> 0) % NET_COLOURS.length;
}

/** A colour per net name: each takes the colour its name hashes to, or the
 * next one no other net on the canvas has, so neighbours rarely match;
 * colours repeat only once every one is in use. */
function colours(names: string[]): Map<string, string> {
  const out = new Map<string, string>();
  const used = new Set<number>();
  for (const name of [...new Set(names)].sort()) {
    if (name === "gnd") { out.set(name, GROUND); continue; }
    let i = preferred(name);
    if (used.size < NET_COLOURS.length) while (used.has(i)) i = (i + 1) % NET_COLOURS.length;
    used.add(i);
    out.set(name, NET_COLOURS[i]);
  }
  return out;
}

function kindOf(raw: Record<string, any> | undefined, type: string | undefined): WNode["kind"] {
  if (type === "group") return "group";
  if (!raw) return "other";
  if (attr(raw, "shape") === "net") return "net";
  if (raw.icon && portsOf(raw).length) return JUNCTION.test(String(raw.icon)) ? "junction" : "symbol";
  return "other";
}

const schematic = (n: WNode | undefined) => !!n && (n.kind === "symbol" || n.kind === "junction" || n.kind === "net");

/** Is this edge a wire? Both ends on a schematic part's pins, and not set to "direct". */
export function isWireEdge(raw: Record<string, any> | undefined, from: Record<string, any> | undefined,
  to: Record<string, any> | undefined): boolean {
  if (!raw || typeof raw.fromPort !== "string" || typeof raw.toPort !== "string") return false;
  if (attr(raw, "pathfindingMethod") === "direct") return false;
  const s = kindOf(from, from?.type), t = kindOf(to, to?.type);
  return s !== "other" && s !== "group" && t !== "other" && t !== "group";
}

// --- reading the store ------------------------------------------------------

let lastNodes: unknown, lastEdges: unknown, lastKey = "";

/** Everything wire routing depends on, as a string so selectors compare by value. */
export function wireKey(s: ReactFlowState): string {
  if (s.nodes === lastNodes && s.edges === lastEdges) return lastKey;
  const nodes: WNode[] = [];
  for (const n of s.nodeLookup.values()) {
    if (n.hidden) continue;
    const raw = (n.data as { raw?: Record<string, any> })?.raw;
    const kind = kindOf(raw, n.type);
    const { x, y } = n.internals.positionAbsolute;
    nodes.push({
      id: n.id, kind, x, y, w: n.width ?? n.measured?.width ?? 0, h: n.height ?? n.measured?.height ?? 0,
      ports: kind === "other" || kind === "group" ? [] : portsOf(raw),
      ...(kind === "net" ? { net: String(raw?.text ?? "").trim().toLowerCase() } : {}),
      ...(n.dragging ? { drag: true as const } : {}),
      ...(kind === "symbol" && /^icons\/sym-ground\//.test(String(raw?.icon)) ? { ground: true as const } : {}),
    });
    const node = nodes[nodes.length - 1];
    if (kind === "symbol" && raw?.text) node.caption = captionBox(node, raw);
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: WEdge[] = [];
  for (const e of s.edges) {
    const raw = (e.data as { raw?: Record<string, any> })?.raw;
    if (!raw || attr(raw, "pathfindingMethod") === "direct") continue;
    if (!schematic(byId.get(e.source)) || !schematic(byId.get(e.target))) continue;
    const sp = portFromHandle(e.sourceHandle), tp = portFromHandle(e.targetHandle);
    if (!sp || !tp) continue;
    edges.push({ id: e.id, source: e.source, target: e.target, sp, tp, label: raw.label || undefined });
  }
  lastNodes = s.nodes;
  lastEdges = s.edges;
  lastKey = edges.length ? JSON.stringify({ nodes, edges } satisfies Input) : "";
  return lastKey;
}

// Roughly the caption's box: 12px text, about 7px a character, 16px a line.
function captionBox(n: Box, raw: Record<string, any>): Box {
  const lines = String(raw.text).split("\n");
  const w = Math.max(...lines.map((l) => l.length)) * 7, h = lines.length * 16;
  switch (captionSide(raw)) {
    case "bottom": return { x: n.x + n.w / 2 - w / 2, y: n.y + n.h + 2, w, h };
    case "top": return { x: n.x + n.w / 2 - w / 2, y: n.y - 2 - h, w, h };
    case "right": return { x: n.x + n.w + 4, y: n.y + n.h / 2 - h / 2, w, h };
    default: return { x: n.x - 4 - w, y: n.y + n.h / 2 - h / 2, w, h };
  }
}

// --- one wire -----------------------------------------------------------------
// The same orthogonal A* as routing.ts (grid lines MARGIN outside each part,
// a cost per bend), but with everything a step needs worked out up front on
// the grid: which points and steps are blocked, and what each step costs
// against the wires already drawn. That keeps a whole schematic routable on
// every change.

function lowerBound(a: number[], v: number): number {
  let lo = 0, hi = a.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < v) lo = m + 1; else hi = m; }
  return lo;
}

/** Indices i with lo < a[i] < hi. */
function inside(a: number[], lo: number, hi: number): [number, number] {
  return [lowerBound(a, lo + 1e-9) , lowerBound(a, hi - 1e-9)];
}

function wireRoute(s: Pt, sSide: Side, t: Pt, tSide: Side, obstacles: Rect[], avoid: Seg[]): Pt[] | null {
  const m = WIRE_MARGIN;
  const sd = SIDE_DIR[sSide], td = SIDE_DIR[tSide];
  const s1 = { x: s.x + DIRS[sd].x * m, y: s.y + DIRS[sd].y * m };
  const t1 = { x: t.x + DIRS[td].x * m, y: t.y + DIRS[td].y * m };
  const bx0 = Math.min(s1.x, t1.x) - REACH, bx1 = Math.max(s1.x, t1.x) + REACH;
  const by0 = Math.min(s1.y, t1.y) - REACH, by1 = Math.max(s1.y, t1.y) + REACH;
  const near = obstacles.filter((r) => r.x1 > bx0 && r.x0 < bx1 && r.y1 > by0 && r.y0 < by1);
  const segs = avoid.filter(({ a, b }) => Math.max(a.x, b.x) >= bx0 && Math.min(a.x, b.x) <= bx1
    && Math.max(a.y, b.y) >= by0 && Math.min(a.y, b.y) <= by1);

  const xs = new Set([s1.x, t1.x, (s1.x + t1.x) / 2]);
  const ys = new Set([s1.y, t1.y, (s1.y + t1.y) / 2]);
  for (const r of near) { xs.add(r.x0 - m); xs.add(r.x1 + m); ys.add(r.y0 - m); ys.add(r.y1 + m); }
  // Lanes beside wires already drawn, so this one can run parallel instead of on top.
  for (const { a, b } of segs) {
    if (a.y === b.y) { ys.add(a.y - m); ys.add(a.y + m); } else { xs.add(a.x - m); xs.add(a.x + m); }
  }
  const X = [...xs].sort((a, b) => a - b), Y = [...ys].sort((a, b) => a - b);
  const nx = X.length, ny = Y.length;
  const idx = (i: number, j: number) => i * ny + j;

  // Blocked: grid points strictly inside a part's zone, and steps through one.
  // Zones stop 1px short of the grid lines, so the lines themselves stay free.
  const blockedPt = new Uint8Array(nx * ny);
  const blockedH = new Uint8Array(nx * ny); // step (i,j) -> (i+1,j)
  const blockedV = new Uint8Array(nx * ny); // step (i,j) -> (i,j+1)
  const midX = X.slice(1).map((x, i) => (X[i] + x) / 2), midY = Y.slice(1).map((y, j) => (Y[j] + y) / 2);
  for (const r of near) {
    const z = { x0: r.x0 - m + 1, y0: r.y0 - m + 1, x1: r.x1 + m - 1, y1: r.y1 + m - 1 };
    const [i0, i1] = inside(X, z.x0, z.x1), [j0, j1] = inside(Y, z.y0, z.y1);
    for (let i = i0; i < i1; i++) for (let j = j0; j < j1; j++) blockedPt[idx(i, j)] = 1;
    const [h0, h1] = inside(midX, z.x0, z.x1);
    for (let i = h0; i < h1; i++) for (let j = j0; j < j1; j++) blockedH[idx(i, j)] = 1;
    const [v0, v1] = inside(midY, z.y0, z.y1);
    for (let i = i0; i < i1; i++) for (let j = v0; j < v1; j++) blockedV[idx(i, j)] = 1;
  }

  // Cost of each step against other nets' wires: running along one, or
  // crossing one (half at each end of a step that crosses at a grid point,
  // so passing through costs one crossing and touching costs half of one).
  const costH = new Float64Array(nx * ny), costV = new Float64Array(nx * ny);
  for (const { a, b } of segs) {
    if (a.y === b.y) {
      const lo = Math.min(a.x, b.x), hi = Math.max(a.x, b.x);
      const j = Y.indexOf(a.y);
      if (j >= 0) {
        const [h0, h1] = inside(midX, lo, hi);
        for (let i = h0; i < h1; i++) costH[idx(i, j)] += OVERLAP;
      }
      // Vertical steps crossing this horizontal wire.
      const [i0, i1] = [lowerBound(X, lo + 1e-9), lowerBound(X, hi - 1e-9)];
      for (let i = i0; i < i1; i++) {
        if (j >= 0) {
          if (j > 0) costV[idx(i, j - 1)] += CROSS / 2;
          if (j < ny - 1) costV[idx(i, j)] += CROSS / 2;
        } else {
          const k = lowerBound(Y, a.y) - 1; // the step spanning a.y
          if (k >= 0 && k < ny - 1) costV[idx(i, k)] += CROSS;
        }
      }
    } else {
      const lo = Math.min(a.y, b.y), hi = Math.max(a.y, b.y);
      const i = X.indexOf(a.x);
      if (i >= 0) {
        const [v0, v1] = inside(midY, lo, hi);
        for (let j = v0; j < v1; j++) costV[idx(i, j)] += OVERLAP;
      }
      const [j0, j1] = [lowerBound(Y, lo + 1e-9), lowerBound(Y, hi - 1e-9)];
      for (let j = j0; j < j1; j++) {
        if (i >= 0) {
          if (i > 0) costH[idx(i - 1, j)] += CROSS / 2;
          if (i < nx - 1) costH[idx(i, j)] += CROSS / 2;
        } else {
          const k = lowerBound(X, a.x) - 1;
          if (k >= 0 && k < nx - 1) costH[idx(k, j)] += CROSS;
        }
      }
    }
  }

  const si = X.indexOf(s1.x), sj = Y.indexOf(s1.y), ti = X.indexOf(t1.x), tj = Y.indexOf(t1.y);
  const arrive = (td + 2) % 4;
  const key = (i: number, j: number, d: number) => idx(i, j) * 4 + d;
  const g = new Map<number, number>();
  const prev = new Map<number, number>();
  const h = (i: number, j: number) => Math.abs(X[i] - t1.x) + Math.abs(Y[j] - t1.y);
  const open = new Heap();
  const start = key(si, sj, sd);
  g.set(start, 0);
  open.push(h(si, sj), start);
  let goal = -1;
  let budget = BUDGET;
  while (open.size && budget-- > 0) {
    const k = open.pop();
    const d = k % 4, ij = (k - d) / 4, j = ij % ny, i = (ij - j) / ny;
    const gk = g.get(k)!;
    if (i === ti && j === tj) { goal = k; break; }
    for (let nd = 0; nd < 4; nd++) {
      if (nd === (d + 2) % 4) continue;
      const ni = i + DIRS[nd].x, nj = j + DIRS[nd].y;
      if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
      const isGoal = ni === ti && nj === tj;
      if (!isGoal && blockedPt[idx(ni, nj)]) continue;
      const horiz = nd % 2 === 0;
      const step = horiz ? idx(Math.min(i, ni), j) : idx(i, Math.min(j, nj));
      if ((horiz ? blockedH : blockedV)[step]) continue;
      let cost = gk + Math.abs(X[ni] - X[i]) + Math.abs(Y[nj] - Y[j]) + (nd === d ? 0 : BEND)
        + (horiz ? costH : costV)[step];
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
    pts.push({ x: X[(ij - j) / ny], y: Y[j] });
  }
  pts.push(s);
  pts.reverse();
  return simplify(pts);
}

// --- routing all wires ------------------------------------------------------

const cache = new Map<string, Map<string, Wire>>();

/** Every wire's drawing for this state of the canvas (cached per key). */
export function wiresFor(key: string): Map<string, Wire> {
  if (!key) return new Map();
  let out = cache.get(key);
  if (!out) {
    out = route(JSON.parse(key) as Input);
    cache.set(key, out);
    if (cache.size > 8) cache.delete(cache.keys().next().value!);
  }
  return out;
}

function pin(n: WNode, port: Port): [Pt, Side] {
  const p = port.side === "left" ? { x: n.x, y: n.y + port.at * n.h }
    : port.side === "right" ? { x: n.x + n.w, y: n.y + port.at * n.h }
    : port.side === "top" ? { x: n.x + port.at * n.w, y: n.y }
    : { x: n.x + port.at * n.w, y: n.y + n.h };
  return [{ x: Math.round(p.x * 10) / 10, y: Math.round(p.y * 10) / 10 }, port.side];
}

/** Which net each pin is on: wires join their two pins, a junction joins all of
 * its own, and net labels with the same name are one net. */
function nets(nodes: Map<string, WNode>, edges: WEdge[]) {
  const parent = new Map<string, string>();
  const find = (k: string): string => {
    let r = k;
    while (parent.has(r) && parent.get(r) !== r) r = parent.get(r)!;
    parent.set(k, r);
    return r;
  };
  const union = (a: string, b: string) => { parent.set(find(a), find(b)); };
  const pinKey = (nodeId: string, port: string) => {
    const n = nodes.get(nodeId);
    if (n?.kind === "junction") return `j:${nodeId}`;
    if (n?.kind === "net") return `n:${n.net}`;
    return `p:${nodeId}:${port}`;
  };
  for (const e of edges) union(pinKey(e.source, e.sp!), pinKey(e.target, e.tp!));
  // A net's name: a net label's, "gnd" if it reaches a ground symbol, else its
  // first pin, so the name (and colour) holds while unrelated wires change.
  const names = new Map<string, string>();
  const rank = (k: string) => (k.startsWith("n:") ? 0 : k === "gnd" ? 1 : 2);
  const offer = (root: string, k: string) => {
    const was = names.get(root);
    if (was === undefined || rank(k) < rank(was) || (rank(k) === rank(was) && k < was)) names.set(root, k);
  };
  for (const e of edges) {
    for (const [node, port] of [[e.source, e.sp!], [e.target, e.tp!]] as const) {
      const k = pinKey(node, port);
      offer(find(k), nodes.get(node)?.ground ? "gnd" : k);
    }
  }
  const nameOf = (e: WEdge) => {
    const n = names.get(find(pinKey(e.source, e.sp!))) ?? "";
    return n.startsWith("n:") ? n.slice(2) : n;
  };
  return { netOf: (e: WEdge) => find(pinKey(e.source, e.sp!)), pinKey, nameOf };
}

function segs(pts: Pt[]): Seg[] {
  return pts.slice(1).map((b, i) => ({ a: pts[i], b }));
}

function route(input: Input): Map<string, Wire> {
  const nodes = new Map(input.nodes.map((n) => [n.id, n]));
  const obstacles: Rect[] = input.nodes
    .filter((n) => n.kind !== "group" && n.w > 0 && n.h > 0)
    .flatMap((n) => [n, ...(n.caption ? [n.caption] : [])])
    .map((b) => ({ x0: b.x, y0: b.y, x1: b.x + b.w, y1: b.y + b.h }));
  const { netOf, pinKey, nameOf } = nets(nodes, input.edges);

  type Job = { e: WEdge; s: Pt; ss: Side; t: Pt; ts: Side; net: string };
  const jobs: Job[] = [];
  for (const e of input.edges) {
    const a = nodes.get(e.source), b = nodes.get(e.target);
    const pa = a?.ports.find((p) => p.id === e.sp), pb = b?.ports.find((p) => p.id === e.tp);
    if (!a || !b || !pa || !pb) continue;
    const [s, ss] = pin(a, pa), [t, ts] = pin(b, pb);
    jobs.push({ e, s, ss, t, ts, net: netOf(e) });
  }
  // Short wires first: they have the fewest ways round, and long ones can go around them.
  jobs.sort((x, y) => (Math.abs(x.s.x - x.t.x) + Math.abs(x.s.y - x.t.y)) - (Math.abs(y.s.x - y.t.x) + Math.abs(y.s.y - y.t.y))
    || (x.e.id < y.e.id ? -1 : 1));

  // Mid-drag, wires not on a moving part keep the routes they had at the last
  // full pass (if their pins haven't moved); the rest route around them. The
  // drop re-routes everything.
  const dragging = input.nodes.some((n) => n.drag);
  const done: { job: Job; pts: Pt[] }[] = [];
  const todo: Job[] = [];
  for (const job of jobs) {
    const was = dragging ? settled.get(job.e.id) : undefined;
    const moving = nodes.get(job.e.source)?.drag || nodes.get(job.e.target)?.drag;
    if (was && !moving && same(was.pts[0], job.s) && same(was.pts[was.pts.length - 1], job.t)) done.push({ job, pts: was.pts });
    else todo.push(job);
  }
  for (const job of todo) {
    const avoid = done.filter((d) => d.job.net !== job.net).flatMap((d) => segs(d.pts));
    const pts = wireRoute(job.s, job.ss, job.t, job.ts, obstacles, avoid)
      ?? wireRoute(job.s, job.ss, job.t, job.ts, [], [])
      ?? [job.s, job.t];
    done.push({ job, pts });
  }
  if (!dragging) settled = new Map(done.map((d) => [d.job.e.id, { pts: d.pts }]));

  // Hops: where wires of different nets cross, the horizontal one jumps the vertical one.
  const hops = new Map<string, Pt[]>();
  for (let i = 0; i < done.length; i++) {
    for (let j = 0; j < done.length; j++) {
      if (i === j || done[i].job.net === done[j].job.net) continue;
      for (const h of segs(done[i].pts)) {
        if (h.a.y !== h.b.y) continue;
        const [x0, x1] = [Math.min(h.a.x, h.b.x), Math.max(h.a.x, h.b.x)];
        for (const v of segs(done[j].pts)) {
          if (v.a.x !== v.b.x) continue;
          const [y0, y1] = [Math.min(v.a.y, v.b.y), Math.max(v.a.y, v.b.y)];
          if (v.a.x > x0 + HOP && v.a.x < x1 - HOP && h.a.y > y0 && h.a.y < y1) {
            const list = hops.get(done[i].job.e.id) ?? [];
            list.push({ x: v.a.x, y: h.a.y });
            hops.set(done[i].job.e.id, list);
          }
        }
      }
    }
  }

  // Dots: wires that leave the same pin share their first leg, then split.
  const dots = new Map<string, Pt[]>();
  const atPin = new Map<string, { id: string; pts: Pt[] }[]>();
  for (const { job, pts } of done) {
    const add = (k: string, p: Pt[]) => {
      if (k.startsWith("j:")) return; // a junction is its own dot
      atPin.set(k, [...(atPin.get(k) ?? []), { id: job.e.id, pts: p }]);
    };
    add(`${pinKey(job.e.source, job.e.sp!)}@${job.e.source}`, pts);
    add(`${pinKey(job.e.target, job.e.tp!)}@${job.e.target}`, [...pts].reverse());
  }
  for (const group of atPin.values()) {
    if (group.length < 2) continue;
    const found: Pt[] = [];
    for (let i = 0; i < group.length; i++) {
      for (let j = i + 1; j < group.length; j++) {
        const p = split(group[i].pts, group[j].pts);
        if (p && !found.some((q) => q.x === p.x && q.y === p.y)) found.push(p);
      }
    }
    if (!found.length) continue;
    const list = dots.get(group[0].id) ?? [];
    for (const p of found) if (!list.some((q) => same(p, q))) list.push(p);
    dots.set(group[0].id, list);
  }

  const palette = colours(done.map((d) => nameOf(d.job.e)));
  const out = new Map<string, Wire>();
  for (const { job, pts } of done) {
    const label = job.e.label ? labelPoint(pts, String(job.e.label).length * 6 + 12, 18, obstacles, []) : pts[0];
    out.set(job.e.id, { d: hopPath(pts, hops.get(job.e.id) ?? []), label, dots: dots.get(job.e.id) ?? [],
      color: palette.get(nameOf(job.e))! });
  }
  return out;
}

const same = (a: Pt, b: Pt) => a.x === b.x && a.y === b.y;
let settled = new Map<string, { pts: Pt[] }>();

const dir = (a: Pt, b: Pt) => `${Math.sign(b.x - a.x)},${Math.sign(b.y - a.y)}`;
const dist = (a: Pt, b: Pt) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);

/** Where two routes from the same pin part: the end of their shared stretch. */
function split(a: Pt[], b: Pt[]): Pt | null {
  let i = 0;
  while (i + 1 < a.length && i + 1 < b.length) {
    if (dir(a[i], a[i + 1]) !== dir(b[i], b[i + 1])) return i === 0 ? null : a[i];
    const na = a[i + 1], nb = b[i + 1];
    if (na.x === nb.x && na.y === nb.y) { i++; continue; }
    // Same way, different lengths: they part where the shorter leg ends.
    return dist(a[i], na) < dist(a[i], nb) ? na : nb;
  }
  return null;
}

/** Square-cornered path through `pts`, jumping each hop point with a small arc. */
function hopPath(pts: Pt[], hops: Pt[]): string {
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    if (a.y === b.y && hops.length) {
      const sgn = Math.sign(b.x - a.x);
      const on = hops.filter((h) => h.y === a.y && (h.x - a.x) * sgn > HOP && (b.x - h.x) * sgn > HOP)
        .sort((p, q) => (p.x - q.x) * sgn);
      for (const h of on) {
        d += ` L ${h.x - sgn * HOP} ${h.y} A ${HOP} ${HOP} 0 0 ${sgn > 0 ? 1 : 0} ${h.x + sgn * HOP} ${h.y}`;
      }
    }
    d += ` L ${b.x} ${b.y}`;
  }
  return d;
}
