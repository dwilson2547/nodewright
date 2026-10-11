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

// Attachments: a file node whose `file` is "attachments/<id>/<name>".
const ATTACHMENT = /^attachments\/([0-9a-f]{32})(?:\/(.*))?$/;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|avif)$/i;

let attachmentUrl = (id: string) => `/api/attachments/${id}`;

/** The render view (Render.tsx) has no session; it fetches attachments by ticket. */
export function setAttachmentUrl(fn: (id: string) => string) {
  attachmentUrl = fn;
}

export function attachmentOf(file: string): { id: string; name: string; url: string; image: boolean } | undefined {
  const m = ATTACHMENT.exec(file);
  if (!m) return undefined;
  const name = m[2] || "file";
  return { id: m[1], name, url: attachmentUrl(m[1]), image: IMAGE_EXT.test(name) };
}
