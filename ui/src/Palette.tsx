import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api, type Icon, type JsonCanvas, type LibraryInfo, type Org, type Template, type TemplateKind } from "./api";
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

/** Share one of your templates or icons with an org, or take it back (design §20). */
function ShareControl({ item, orgs, onPick }: {
  item: LibraryInfo;
  orgs: Org[];
  onPick: (orgId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!item.mine || (!orgs.length && !item.org)) return null;
  if (!open) {
    return (
      <button className="tab-x" title={item.org ? `Shared with ${item.org.name}: change` : "Share with an organisation"}
        onClick={() => setOpen(true)}>⇄</button>
    );
  }
  return (
    <select className="palette-share" autoFocus value={item.org?.id ?? ""} aria-label="Share with"
      onBlur={() => setOpen(false)}
      onChange={(e) => { setOpen(false); onPick(e.target.value || null); }}>
      <option value="">Only me</option>
      {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      {item.org && !orgs.some((o) => o.id === item.org!.id) && <option value={item.org.id}>{item.org.name}</option>}
    </select>
  );
}

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
function Icons({ editable, orgs, onIcon, fail }: {
  editable: boolean;
  orgs: Org[];
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
    const shared = i.org ? ` It's shared with ${i.org.name}, so it goes for everyone there.` : "";
    if (!confirm(`Delete the icon "${i.name}"? Nodes using it will show "missing icon".${shared}`)) return;
    await api.deleteIcon(i.id).then(load, fail);
  };
  const share = async (i: Icon, orgId: string | null) => {
    await api.patchIcon(i.id, { org_id: orgId }).then(load, fail);
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
          <div key={i.id} className={"palette-icon" + (i.builtin ? "" : " mine") + (i.org ? " org" : "")}>
            <button className="palette-insert" draggable={editable} disabled={!editable} onDragStart={drag(i)}
              onClick={() => onIcon(i)}
              title={(i.org ? `${i.name} (${i.org.name})` : i.name) + (editable ? ": click to add (or put on the selected text box), or drag" : "")}>
              {i.tinted
                ? <span className="glyph" style={{ mask: `url("${i.url}?v=${bust}") center / contain no-repeat`, WebkitMask: `url("${i.url}?v=${bust}") center / contain no-repeat` }} />
                : <img className="glyph" src={`${i.url}?v=${bust}`} alt="" />}
            </button>
            {i.can_edit && <button className="tab-x" title="Delete icon" onClick={() => void remove(i)}>×</button>}
            {i.editable && i.can_edit && editable && <button className="tab-x edit" title="Edit in the icon creator" onClick={() => setCreating(i)}>✎</button>}
            <span className="palette-icon-share"><ShareControl item={i} orgs={orgs} onPick={(o) => void share(i, o)} /></span>
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

// Schematic symbols (design §15): built-in icons with pins, by category, and
// net labels. Placed like icons; the symbol's pins become the node's ports.
function Symbols({ editable, onIcon, onNetLabel, fail }: {
  editable: boolean;
  onIcon: (icon: Icon) => void;
  onNetLabel: () => void;
  fail: (e: unknown) => void;
}) {
  const [symbols, setSymbols] = useState<Icon[]>([]);
  const [q, setQ] = useState("");
  useEffect(() => { api.icons().then((r) => setSymbols(r.symbols), fail); }, [fail]);
  const drag = (i: Icon) => (e: DragEvent) => {
    e.dataTransfer.setData(ICON_DRAG_TYPE, JSON.stringify(i));
    e.dataTransfer.effectAllowed = "copy";
  };
  const shown = symbols.filter((i) => !q || i.name.toLowerCase().includes(q.toLowerCase()));
  const groups = [...new Set(shown.map((i) => i.category ?? ""))];
  return (
    <section>
      <h5>Symbols</h5>
      <input className="palette-search" type="search" placeholder="Search symbols" value={q}
        onChange={(e) => setQ(e.target.value)} aria-label="Search symbols" />
      {editable && (
        <button className="palette-save" onClick={onNetLabel}
          title="A named net: wires on labels with the same name are connected">+ Net label</button>
      )}
      {groups.map((g) => (
        <div key={g}>
          <div className="palette-sub">{g}</div>
          <div className="palette-icons">
            {shown.filter((i) => (i.category ?? "") === g).map((i) => (
              <div key={i.id} className="palette-icon">
                <button className="palette-insert" draggable={editable} disabled={!editable} onDragStart={drag(i)}
                  onClick={() => onIcon(i)} title={editable ? `${i.name}: click to add, or drag` : i.name}>
                  <span className="glyph" style={{ mask: `url("${i.url}") center / contain no-repeat`, WebkitMask: `url("${i.url}") center / contain no-repeat` }} />
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

type Props = {
  editable: boolean;
  reloadKey: number;
  onInsert: (t: Template) => void;
  onIcon: (icon: Icon) => void;
  onNetLabel: () => void;
  onSavePage: () => Promise<void>;
  onClose: () => void;
};

export function Palette({ editable, reloadKey, onInsert, onIcon, onNetLabel, onSavePage, onClose }: Props) {
  const [list, setList] = useState<Template[]>([]);
  const [defaultPage, setDefaultPage] = useState("");
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback((e: unknown) => setError(e instanceof Error ? e.message : String(e)), []);

  const load = useCallback(() => {
    api.templates().then((r) => {
      setList(r.templates);
      setDefaultPage(r.default_page);
    }, (e) => setError(String(e.message || e)));
  }, []);
  useEffect(load, [load, reloadKey]);
  useEffect(() => { api.orgs().then((r) => setOrgs(r.orgs), () => undefined); }, [reloadKey]);

  const drag = (t: Template) => (e: DragEvent) => {
    e.dataTransfer.setData(DRAG_TYPE, t.id);
    e.dataTransfer.effectAllowed = "copy";
  };

  const remove = async (t: Template) => {
    const shared = t.org ? ` It's shared with ${t.org.name}, so it goes for everyone there.` : "";
    if (!confirm(`Delete the template "${t.name}"?${shared}`)) return;
    await api.deleteTemplate(t.id).catch((e) => setError(String(e.message || e)));
    load();
  };

  const rename = async (t: Template) => {
    const name = prompt("Template name", t.name)?.trim();
    if (!name || name === t.name) return;
    await api.renameTemplate(t.id, name).catch((e) => setError(String(e.message || e)));
    load();
  };

  const share = async (t: Template, orgId: string | null) => {
    await api.shareTemplate(t.id, orgId).catch((e) => setError(String(e.message || e)));
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
                <div key={t.id} className={"palette-item" + (t.builtin ? "" : " mine") + (t.org ? " org" : "")}>
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
                    {t.org && <span className="palette-org">{t.org.name}</span>}
                  </button>
                  <div className="palette-actions">
                    {kind === "page" && (
                      <button className={"tab-x" + (defaultPage === t.id ? " on" : "")}
                        title={defaultPage === t.id ? "New tabs start from this page" : "Start new tabs from this page"}
                        onClick={() => void makeDefault(t)}>{defaultPage === t.id ? "★" : "☆"}</button>
                    )}
                    {t.can_edit && <>
                      <button className="tab-x" title="Rename" onClick={() => void rename(t)}>✎</button>
                      <button className="tab-x" title="Delete" onClick={() => void remove(t)}>×</button>
                    </>}
                    <ShareControl item={t} orgs={orgs} onPick={(o) => void share(t, o)} />
                  </div>
                </div>
              ))}
            </div>
            {kind === "page" && <button className="palette-save" onClick={() => void savePage()}>Save this canvas as a page…</button>}
          </section>
        );
      })}
      <Symbols editable={editable} onIcon={onIcon} onNetLabel={onNetLabel} fail={fail} />
      <Icons editable={editable} orgs={orgs} onIcon={onIcon} fail={fail} />
      <p className="muted small">
        Select nodes and use <em>Save as template</em> to add your own shapes and snippets.
        {orgs.length > 0 && <> Use ⇄ on one of yours to share it with an organisation.</>}
      </p>
    </aside>
  );
}
