// Icons on text nodes (design §13.2, api/nodewright/icons.py): a node's
// `icon` is the vault path "icons/<id>/<name>.svg"; the API serves it at
// /api/icons/<id>.svg to anyone, so share links and render pages show it too.
const REF_RE = /^icons\/([a-z0-9-]{1,64})\/[^/]{1,200}\.svg$/;

export const ICON_DRAG_TYPE = "application/x-nodewright-icon";

export function iconUrl(ref: unknown): string | null {
  const m = typeof ref === "string" ? REF_RE.exec(ref) : null;
  return m ? `/api/icons/${m[1]}.svg` : null;
}
