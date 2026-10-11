import { memo } from "react";
import type { CEdge } from "./canvasMapping";
import { markerId, resolveColor, DEFAULT_COLOR } from "./canvasMapping";
import { attr } from "./styles";

const SIZE = 16;

// Each shape in a 10x10 box with its tip at (10, 5); "solid" shapes are filled
// with the edge colour, "open" ones with the canvas background.
function shape(arrow: string, color: string) {
  const solid = { fill: color, stroke: color, strokeWidth: 1 };
  const open = { fill: "var(--bg)", stroke: color, strokeWidth: 1.4 };
  switch (arrow) {
    case "triangle-outline": return <path d="M1 1 L10 5 L1 9 Z" style={open} />;
    case "thin-triangle": return <path d="M1 1 L10 5 L1 9" style={{ ...open, fill: "none", strokeLinejoin: "round" }} />;
    case "halved-triangle": return <path d="M0 0.5 L10 5 L0 5 Z" style={solid} />;
    case "diamond": return <path d="M0 5 L5 1.5 L10 5 L5 8.5 Z" style={solid} />;
    case "diamond-outline": return <path d="M0.5 5 L5 1.5 L9.5 5 L5 8.5 Z" style={open} />;
    case "circle": return <circle cx="6" cy="5" r="3.5" style={solid} />;
    case "circle-outline": return <circle cx="6" cy="5" r="3.5" style={open} />;
    case "blunt": return <path d="M9 0.5 V9.5" style={{ ...open, strokeWidth: 2 }} />;
    default: return <path d="M0 0.5 L10 5 L0 9.5 Z" style={solid} />;
  }
}

/** The <marker> definitions the edges refer to (canvasMapping.edgeVisual). */
export const Markers = memo(function Markers({ edges }: { edges: CEdge[] }) {
  const seen = new Map<string, [string, string]>();
  for (const e of edges) {
    const raw = e.data?.raw ?? {};
    const color = resolveColor(raw.color) ?? DEFAULT_COLOR;
    const arrow = attr(raw, "arrow");
    seen.set(markerId(arrow, color), [arrow, color]);
  }
  return (
    <svg className="nw-markers" aria-hidden="true">
      <defs>
        {[...seen].map(([id, [arrow, color]]) => (
          <marker key={id} id={id} viewBox="0 0 10 10" refX="10" refY="5" markerWidth={SIZE} markerHeight={SIZE}
            markerUnits="userSpaceOnUse" orient="auto-start-reverse">
            {shape(arrow, color)}
          </marker>
        ))}
      </defs>
    </svg>
  );
});
