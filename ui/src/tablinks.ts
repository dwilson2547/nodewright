import { createContext } from "react";
import type { CanvasMeta } from "./api";

// A file node whose `file` is "<tab name>.canvas" links to that tab of the
// same workspace (Obsidian's convention for linking canvases); an optional
// `subpath` "#<node id>" focuses a node there.

export type TabLinks = {
  tabs: CanvasMeta[];
  current: string | null;
  open: (canvasId: string, nodeId?: string) => void;
};

export const TabLinksContext = createContext<TabLinks>({ tabs: [], current: null, open: () => undefined });

const EXT = ".canvas";

export const isCanvasFile = (file: string) => file.toLowerCase().endsWith(EXT);

export const canvasFile = (name: string) => name + EXT;

export function linkTarget(file: string, tabs: CanvasMeta[]): CanvasMeta | undefined {
  if (!isCanvasFile(file)) return undefined;
  const full = file.slice(0, -EXT.length);
  const base = full.split("/").pop() ?? full;
  for (const name of [full, base]) {
    const hit = tabs.find((t) => t.name === name) ?? tabs.find((t) => t.name.toLowerCase() === name.toLowerCase());
    if (hit) return hit;
  }
  return undefined;
}

export const subpathNode = (subpath?: string) => (subpath ? subpath.replace(/^#\^?/, "") || undefined : undefined);
