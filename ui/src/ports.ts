// Node ports (design §13.1, api/nodewright/ports.py): named connection points
// at a fraction along one side. A node with ports shows them instead of the
// four side handles; an edge names one with fromPort/toPort and keeps
// fromSide/toSide equal to its side. An edge whose port has gone falls back
// to its side and is flagged.
export type Side = "top" | "right" | "bottom" | "left";
export type Port = { id: string; side: Side; at: number; label?: string };

export const SIDES: Side[] = ["top", "right", "bottom", "left"];
const PREFIX = "port:";

export function portsOf(raw: Record<string, any> | undefined): Port[] {
  return Array.isArray(raw?.ports) ? raw!.ports : [];
}

export const portHandle = (id: string) => PREFIX + id;
export const portFromHandle = (handle: string | null | undefined) =>
  handle?.startsWith(PREFIX) ? handle.slice(PREFIX.length) : null;

/** React Flow handle id for one end of an edge, and whether its named port is missing. */
export function endHandle(node: Record<string, any> | undefined, port: unknown, side: string): [string, boolean] {
  if (typeof port !== "string") return [side, false];
  const p = portsOf(node).find((x) => x.id === port);
  return p ? [portHandle(p.id), false] : [side, true];
}

/** Edge raw fields for a connection made to `handle` on `node`. */
export function endFields(node: Record<string, any> | undefined, handle: string | null | undefined,
  end: "from" | "to"): Record<string, string | undefined> {
  const id = portFromHandle(handle);
  const p = id ? portsOf(node).find((x) => x.id === id) : undefined;
  return p
    ? { [`${end}Port`]: p.id, [`${end}Side`]: p.side }
    : { [`${end}Port`]: undefined, [`${end}Side`]: handle ?? undefined };
}

function spread(side: Side, n: number, prefix: string): Port[] {
  return Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i + 1}`, side, at: Math.round(((i + 1) / (n + 1)) * 1000) / 1000 }));
}

export const PRESETS: { value: string; label: string; ports: () => Port[] }[] = [
  { value: "", label: "Side handles", ports: () => [] },
  { value: "lr1", label: "1 in, 1 out", ports: () => [...spread("left", 1, "in"), ...spread("right", 1, "out")] },
  { value: "lr2", label: "2 in, 2 out", ports: () => [...spread("left", 2, "in"), ...spread("right", 2, "out")] },
  { value: "lr3", label: "3 in, 3 out", ports: () => [...spread("left", 3, "in"), ...spread("right", 3, "out")] },
  { value: "tb1", label: "1 top, 1 bottom", ports: () => [...spread("top", 1, "t"), ...spread("bottom", 1, "b")] },
  { value: "all2", label: "2 per side", ports: () => SIDES.flatMap((s) => spread(s, 2, s[0])) },
];

export function nextPortId(ports: Port[]): string {
  const used = new Set(ports.map((p) => p.id));
  let i = ports.length + 1;
  while (used.has(`p${i}`)) i++;
  return `p${i}`;
}

// --- orientation (design §15, ports.py): styleAttributes rotate (90/180/270,
// clockwise) and mirror ("horizontal", applied before rotating). Stored ports
// are where the pins are drawn, so turning a node moves them.
export type Orientation = { rotate: number; mirror: boolean };

const CW: Record<Side, Side> = { left: "top", top: "right", right: "bottom", bottom: "left" };
const point = (p: Port): [number, number] =>
  p.side === "left" ? [0, p.at] : p.side === "right" ? [1, p.at] : p.side === "top" ? [p.at, 0] : [p.at, 1];
const along = (side: Side, x: number, y: number) => Math.round((side === "left" || side === "right" ? y : x) * 1e4) / 1e4;

function rotateCw(p: Port): Port {
  const [x, y] = point(p);
  const side = CW[p.side];
  return { ...p, side, at: along(side, 1 - y, x) };
}

/** Mirror left-right in the node's own frame (and on screen, before any rotation). */
export function mirrorPort(p: Port): Port {
  const [x, y] = point(p);
  const side: Side = p.side === "left" ? "right" : p.side === "right" ? "left" : p.side;
  return { ...p, side, at: along(side, 1 - x, y) };
}

export function orientationOf(raw: Record<string, any> | undefined): Orientation {
  const sa = raw?.styleAttributes ?? {};
  return { rotate: (Number(sa.rotate) || 0) % 360, mirror: sa.mirror === "horizontal" };
}

/** Pins drawn upright at `pins`, placed at orientation `o` (as the server does for agents). */
export function orient(pins: Port[], o: Orientation): Port[] {
  return pins.map((p) => {
    let q = o.mirror ? mirrorPort(p) : p;
    for (let i = 0; i < o.rotate / 90; i++) q = rotateCw(q);
    return q;
  });
}

/** A quarter turn clockwise on screen: the new orientation and where the ports go. */
export function turned(o: Orientation, ports: Port[]): [Orientation, Port[]] {
  return [{ ...o, rotate: (o.rotate + 90) % 360 }, ports.map(rotateCw)];
}

/** A left-right flip on screen. Flipping after a turn r equals mirroring first
 *  and turning by -r, which is how the drawing's transform is written. */
export function flipped(o: Orientation, ports: Port[]): [Orientation, Port[]] {
  return [{ rotate: (360 - o.rotate) % 360, mirror: !o.mirror }, ports.map(mirrorPort)];
}
