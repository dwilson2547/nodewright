// Style extensions (design §3.2). Key names and values are the Obsidian
// Advanced Canvas plugin's `styleAttributes` (src/canvas-extensions/
// advanced-styles/style-config.ts, checked at 4b8630c), so these documents
// render with that plugin too. `lineWidth` and `cornerRadius` are
// nodewright's own: the plugin has neither. An absent key is the default.
export type Option = { value: string; label: string };

export const NODE_SHAPES: Option[] = [
  { value: "", label: "Rectangle" },
  { value: "pill", label: "Rounded" },
  { value: "diamond", label: "Diamond" },
  { value: "parallelogram", label: "Parallelogram" },
  { value: "circle", label: "Ellipse" },
  { value: "predefined-process", label: "Process" },
  { value: "document", label: "Document" },
  { value: "database", label: "Database" },
];

export const NODE_BORDERS: Option[] = [
  { value: "", label: "Solid" },
  { value: "dashed", label: "Dashed" },
  { value: "dotted", label: "Dotted" },
  { value: "invisible", label: "None" },
];

export const TEXT_ALIGN: Option[] = [
  { value: "", label: "Left" },
  { value: "center", label: "Centre" },
  { value: "right", label: "Right" },
];

export const EDGE_PATHS: Option[] = [
  { value: "", label: "Solid" },
  { value: "dotted", label: "Dotted" },
  { value: "short-dashed", label: "Dashed" },
  { value: "long-dashed", label: "Long dash" },
];

export const EDGE_ROUTES: Option[] = [
  { value: "", label: "Curved" },
  { value: "direct", label: "Straight" },
  { value: "square", label: "Right-angle" },
  { value: "a-star", label: "Rounded right-angle" },
];

export const EDGE_ARROWS: Option[] = [
  { value: "", label: "Triangle" },
  { value: "triangle-outline", label: "Open triangle" },
  { value: "thin-triangle", label: "Chevron" },
  { value: "halved-triangle", label: "Half" },
  { value: "diamond", label: "Diamond" },
  { value: "diamond-outline", label: "Open diamond" },
  { value: "circle", label: "Dot" },
  { value: "circle-outline", label: "Open dot" },
  { value: "blunt", label: "Bar" },
];

export const LINE_WIDTHS: Option[] = [
  { value: "1", label: "Thin" },
  { value: "", label: "Normal" },
  { value: "4", label: "Thick" },
  { value: "6", label: "Heavy" },
];

// How a text node's icon is drawn (nodes.tsx IconView); nodewright's own.
export const ICON_COLORS: Option[] = [
  { value: "", label: "Icon in node colour" },
  { value: "original", label: "Icon's own colours" },
];

// Rounding of each bend on a right-angle route or detour (edges.tsx).
export const CORNER_RADII: Option[] = [
  { value: "", label: "Default corners" },
  { value: "0", label: "Sharp corners" },
  ...[4, 8, 12, 16, 24, 32, 48].map((n) => ({ value: String(n), label: `${n}px corners` })),
];

export const DEFAULT_WIDTH = 2;

export function attr(raw: Record<string, any>, key: string): string {
  const v = raw.styleAttributes?.[key];
  return typeof v === "string" ? v : "";
}

/** raw with styleAttributes[key] set, or removed when value is "". */
export function withAttr(raw: Record<string, any>, key: string, value: string): Record<string, any> {
  const sa = { ...(raw.styleAttributes ?? {}) };
  if (value) sa[key] = value;
  else delete sa[key];
  const out = { ...raw, styleAttributes: sa };
  if (Object.keys(sa).length === 0) delete out.styleAttributes;
  return out;
}

export function dashArray(path: string, width: number): string | undefined {
  const w = Math.max(1, width);
  if (path === "dotted") return `0 ${w * 3}`;
  if (path === "short-dashed") return `${w * 3} ${w * 3}`;
  if (path === "long-dashed") return `${w * 7} ${w * 4}`;
  return undefined;
}

/** The edge's corner radius in px, or undefined for the routing's default. */
export function cornerRadius(raw: Record<string, any>): number | undefined {
  const v = attr(raw, "cornerRadius");
  const n = Number(v);
  return v !== "" && n >= 0 && n <= 200 ? n : undefined;
}

export function lineWidth(raw: Record<string, any>): number {
  const n = Number(attr(raw, "lineWidth"));
  return n >= 1 && n <= 12 ? n : DEFAULT_WIDTH;
}
