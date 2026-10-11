import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api, type Icon, type JsonCanvas, type Template, type TemplateKind } from "./api";
import { IconCreator } from "./IconCreator";
import { ICON_DRAG_TYPE } from "./icons";
import { DEFAULT_COLOR, resolveColor } from "./canvasMapping";
import { attr } from "./styles";

export const DRAG_TYPE = "application/x-nodewright-template";

const SECTIONS: [TemplateKind, string][] = [
  ["stencil", "Shapes"],
  ["fragment", "Snippets"],
  ["page", "Pages"],
];

/** A small drawing of a template: outlines and straight edges. */
function Thumb({ doc }: { doc: JsonCanvas }) {
  const nodes: any[] = doc.nodes ?? [];
  if (nodes.length === 0) return <svg className="thumb" viewBox="0 0 72 48" />;
  const W = Math.max(...nodes.map((n) => n.x + n.width)), H = Math.max(...nodes.map((n) => n.y + n.height));
  const by = new Map(nodes.map((n) => [n.id, n]));
  const pad = Math.max(W, H) * 0.04;
  return (
    <svg className="thumb" viewBox={`${-pad} ${-pad} ${W + 2 * pad} ${H + 2 * pad}`} preserveAspectRatio="xMidYMid meet">
      {(doc.edges ?? []).map((e: any) => {
        const a = by.get(e.fromNode), b = by.get(e.toNode);
        if (!a || !b) return null;
        return <line key={e.id} x1={a.x + a.width / 2} y1={a.y + a.height / 2} x2={b.x + b.width / 2} y2={b.y + b.height / 2}
          stroke={resolveColor(e.color) ?? DEFAULT_COLOR} vectorEffect="non-scaling-stroke" strokeWidth={1.2} />;
      })}
      {nodes.map((n) => {
        const c = resolveColor(n.color) ?? "currentColor";
        const p = { stroke: c, fill: n.type === "group" ? "none" : "var(--panel)", vectorEffect: "non-scaling-stroke" as const, strokeWidth: 1.5 };
        const { x, y, width: w, height: h } = n;
        const shape = n.type === "text" ? attr(n, "shape") : "";
        if (shape === "diamond") return <polygon key={n.id} points={`${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}`} {...p} />;
        if (shape === "circle") return <ellipse key={n.id} cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} {...p} />;
        if (shape === "parallelogram") return <polygon key={n.id} points={`${x + w * 0.15},${y} ${x + w},${y} ${x + w * 0.85},${y + h} ${x},${y + h}`} {...p} />;
        const rx = shape === "pill" ? h / 2 : shape === "database" ? w / 2 : Math.min(w, h) * 0.08;
        const ry = shape === "database" ? h * 0.12 : rx;
        return <rect key={n.id} x={x} y={y} width={w} height={h} rx={rx} ry={ry} {...p}
          strokeDasharray={n.type === "group" ? "4 3" : undefined} />;
      })}
    </svg>
  );
}

// Icons (design §13.2): built-ins and the user's own; click to add an icon
// node (or set the icon of the selected text node), drag to place one.
function Icons({ editable, onIcon, fail }: {
  editable: boolean;
  onIcon: (icon: Icon) => void;
  fail: (e: unknown) => void;
}) {
  const [icons, setIcons] = useState<{ builtin: Icon[]; mine: Icon[] }>({ builtin: [], mine: [] });
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState<Icon | "new" | null>(null);
  const [bust, setBust] = useState(0); // reloads previews after an edit keeps the same url
  const file = useRef<HTMLInputElement>(null);
  const load = useCallback(() => { api.icons().then(setIcons, fail); }, [fail]);
  useEffect(load, [load]);

  const upload = async (f: File) => {
    const name = prompt("Icon name", f.name.replace(/\.svg$/i, ""))?.trim();
    if (!name) return;
    const tinted = confirm("Draw this icon in the node's colour?\n\nOK for one-colour line icons; "
      + "Cancel to keep the SVG's own colours.");
    try {
      await api.createIcon({ name, svg: await f.text(), tinted });
      load();
    } catch (e) {
      fail(e);
    }
  };
  const remove = async (i: Icon) => {
    if (!confirm(`Delete the icon "${i.name}"? Nodes using it will show "missing icon".`)) return;
    await api.deleteIcon(i.id).then(load, fail);
  };
  const drag = (i: Icon) => (e: DragEvent) => {
    e.dataTransfer.setData(ICON_DRAG_TYPE, JSON.stringify(i));
    e.dataTransfer.effectAllowed = "copy";
  };
  const match = (i: Icon) => !q || i.name.toLowerCase().includes(q.toLowerCase());
  const all = [...icons.mine, ...icons.builtin].filter(match);

  return (
    <section>
      <h5>Icons</h5>
      <input className="palette-search" type="search" placeholder="Search icons" value={q}
        onChange={(e) => setQ(e.target.value)} aria-label="Search icons" />
      <div className="palette-icons">
        {all.map((i) => (
          <div key={i.id} className={"palette-icon" + (i.builtin ? "" : " mine")}>
            <button className="palette-insert" draggable={editable} disabled={!editable} onDragStart={drag(i)}
              onClick={() => onIcon(i)} title={editable ? `${i.name}: click to add (or put on the selected text box), or drag` : i.name}>
              {i.tinted
                ? <span className="glyph" style={{ mask: `url("${i.url}?v=${bust}") center / contain no-repeat`, WebkitMask: `url("${i.url}?v=${bust}") center / contain no-repeat` }} />
                : <img className="glyph" src={`${i.url}?v=${bust}`} alt="" />}
            </button>
            {!i.builtin && <button className="tab-x" title="Delete icon" onClick={() => void remove(i)}>×</button>}
            {i.editable && editable && <button className="tab-x edit" title="Edit in the icon creator" onClick={() => setCreating(i)}>✎</button>}
          </div>
        ))}
      </div>
      {editable && <>
        <button className="palette-save" onClick={() => setCreating("new")}>Create icon…</button>
        <button className="palette-save" onClick={() => file.current?.click()}>Upload SVG icon…</button>
        <input ref={file} type="file" accept=".svg,image/svg+xml" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void upload(f);
        }} />
      </>}
      {creating && (
        <IconCreator icon={creating === "new" ? undefined : creating} onClose={() => setCreating(null)}
          onSaved={() => { setCreating(null); setBust((b) => b + 1); load(); }} />
      )}
    </section>
  );
}

type Props = {
  editable: boolean;
  reloadKey: number;
  onInsert: (t: Template) => void;
  onIcon: (icon: Icon) => void;
  onSavePage: () => Promise<void>;
  onClose: () => void;
};

export function Palette({ editable, reloadKey, onInsert, onIcon, onSavePage, onClose }: Props) {
  const [list, setList] = useState<Template[]>([]);
  const [defaultPage, setDefaultPage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback((e: unknown) => setError(e instanceof Error ? e.message : String(e)), []);

  const load = useCallback(() => {
    api.templates().then((r) => {
      setList(r.templates);
      setDefaultPage(r.default_page);
    }, (e) => setError(String(e.message || e)));
  }, []);
  useEffect(load, [load, reloadKey]);

  const drag = (t: Template) => (e: DragEvent) => {
    e.dataTransfer.setData(DRAG_TYPE, t.id);
    e.dataTransfer.effectAllowed = "copy";
  };

  const remove = async (t: Template) => {
    if (!confirm(`Delete the template "${t.name}"?`)) return;
    await api.deleteTemplate(t.id).catch((e) => setError(String(e.message || e)));
    load();
  };

  const rename = async (t: Template) => {
    const name = prompt("Template name", t.name)?.trim();
    if (!name || name === t.name) return;
    await api.renameTemplate(t.id, name).catch((e) => setError(String(e.message || e)));
    load();
  };

  const makeDefault = async (t: Template) => {
    try {
      setDefaultPage((await api.setDefaultPage(t.id)).default_page);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const savePage = async () => {
    try {
      await onSavePage();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <aside className="palette" aria-label="Templates">
      <div className="palette-head">
        <strong>Templates</strong>
        <button className="tab-x" onClick={onClose} title="Close">×</button>
      </div>
      {error && <div className="palette-error" onClick={() => setError(null)}>{error}</div>}
      {SECTIONS.map(([kind, title]) => {
        const items = list.filter((t) => t.kind === kind).sort((a, b) => Number(a.builtin) - Number(b.builtin));
        return (
          <section key={kind}>
            <h5>{title}</h5>
            <div className={"palette-grid" + (kind === "stencil" ? "" : " wide")}>
              {items.map((t) => (
                <div key={t.id} className={"palette-item" + (t.builtin ? "" : " mine")}>
                  <button
                    className="palette-insert"
                    draggable={editable}
                    disabled={!editable}
                    onDragStart={drag(t)}
                    onClick={() => onInsert(t)}
                    title={editable ? `${t.name}: click to add, or drag onto the canvas` : t.name}
                  >
                    <Thumb doc={t.data} />
                    <span>{t.name}</span>
                  </button>
                  <div className="palette-actions">
                    {kind === "page" && (
                      <button className={"tab-x" + (defaultPage === t.id ? " on" : "")}
                        title={defaultPage === t.id ? "New tabs start from this page" : "Start new tabs from this page"}
                        onClick={() => void makeDefault(t)}>{defaultPage === t.id ? "★" : "☆"}</button>
                    )}
                    {!t.builtin && <>
                      <button className="tab-x" title="Rename" onClick={() => void rename(t)}>✎</button>
                      <button className="tab-x" title="Delete" onClick={() => void remove(t)}>×</button>
                    </>}
                  </div>
                </div>
              ))}
            </div>
            {kind === "page" && <button className="palette-save" onClick={() => void savePage()}>Save this canvas as a page…</button>}
          </section>
        );
      })}
      <Icons editable={editable} onIcon={onIcon} fail={fail} />
      <p className="muted small">Select nodes and use <em>Save as template</em> to add your own shapes and snippets.</p>
    </aside>
  );
}
