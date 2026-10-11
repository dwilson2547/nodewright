import { createContext, memo, useContext, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Handle, NodeResizer, Position, useReactFlow, useUpdateNodeInternals, type NodeProps } from "@xyflow/react";
import { resolveColor, type CNode } from "./canvasMapping";
import { Markdown, safeUrl } from "./markdown";
import { portHandle, portsOf, type Port } from "./ports";
import { attr } from "./styles";
import { attachmentOf, TabLinksContext, isCanvasFile, linkTarget, subpathNode } from "./tablinks";

const SIDES: [string, Position][] = [
  ["top", Position.Top],
  ["right", Position.Right],
  ["bottom", Position.Bottom],
  ["left", Position.Left],
];

const POSITION: Record<Port["side"], Position> = {
  top: Position.Top, right: Position.Right, bottom: Position.Bottom, left: Position.Left,
};

// Where a port sits along its side, as a handle offset (ports.ts).
const along = (p: Port): CSSProperties =>
  p.side === "left" || p.side === "right" ? { top: `${p.at * 100}%` } : { left: `${p.at * 100}%` };

// Every handle is a "source"; the flow runs in ConnectionMode.Loose, so any
// side or port can connect to any other, as in JSON Canvas. A node with ports
// shows those instead of the side handles, which stay (hidden, not
// connectable) for edges whose port has gone.
function Handles({ id, raw }: { id: string; raw: Record<string, any> }) {
  const ports = portsOf(raw);
  const updateInternals = useUpdateNodeInternals();
  const key = JSON.stringify(ports);
  useEffect(() => updateInternals(id), [id, key, updateInternals]);
  const hasPorts = ports.length > 0;
  return (
    <>
      {SIDES.map(([sid, pos]) => (
        <Handle key={sid} id={sid} type="source" position={pos} isConnectable={!hasPorts}
          className={"nw-handle" + (hasPorts ? " nw-handle-hidden" : "")} />
      ))}
      {ports.map((p) => (
        <Handle key={p.id} id={portHandle(p.id)} type="source" position={POSITION[p.side]}
          className="nw-handle nw-port" style={along(p)} title={p.label || p.id} />
      ))}
      {ports.filter((p) => p.label).map((p) => (
        <span key={"l:" + p.id} className={`nw-port-label side-${p.side}`} style={along(p)}>{p.label}</span>
      ))}
    </>
  );
}

function colorStyle(raw: Record<string, any>): CSSProperties {
  const c = resolveColor(raw.color);
  return c ? ({ "--node-color": c } as CSSProperties) : {};
}

// Shapes CSS can't draw are an SVG outline in a 100x100 box stretched over
// the node; the strokes keep their width (vector-effect in index.css).
const OUTLINES: Record<string, ReactNode> = {
  diamond: <polygon points="50,0 100,50 50,100 0,50" />,
  parallelogram: <polygon points="15,0 100,0 85,100 0,100" />,
  "predefined-process": <><rect x="0" y="0" width="100" height="100" /><path className="line" d="M8 0V100M92 0V100" /></>,
  document: <path d="M0 0H100V86C80 72 62 98 36 95C18 93 8 87 0 89Z" />,
  database: <><path d="M0 10A50 10 0 0 1 100 10V90A50 10 0 0 1 0 90Z" /><path className="line" d="M0 10A50 10 0 0 0 100 10" /></>,
};

/** Class names and outline for a node's style attributes (styles.ts). */
function look(raw: Record<string, any>, kind: string, shapes = false) {
  const shape = shapes ? attr(raw, "shape") : "";
  const border = attr(raw, "border");
  const align = attr(raw, "textAlign");
  const outline = OUTLINES[shape];
  let cls = `nw-node nw-${kind}`;
  if (shape) cls += ` shaped shape-${shape}` + (outline ? " svgshape" : "");
  if (border) cls += ` border-${border}`;
  if (align) cls += ` align-${align}`;
  const svg = outline ? (
    <svg className="nw-outline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{outline}</svg>
  ) : null;
  return { cls, svg };
}

/** True while someone else holds the canvas's edit lease. */
export const ReadOnly = createContext(false);

function useEditable(id: string, raw: Record<string, any>, field: string) {
  const { updateNodeData } = useReactFlow();
  const readOnly = useContext(ReadOnly);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const start = () => {
    if (readOnly) return;
    setDraft(String(raw[field] ?? ""));
    setEditing(true);
  };
  const commit = () => {
    setEditing(false);
    if (draft !== (raw[field] ?? "")) updateNodeData(id, { raw: { ...raw, [field]: draft } });
  };
  const cancel = () => setEditing(false);
  return { editing, draft, setDraft, start, commit, cancel };
}

function Editor({ value, onChange, onCommit, onCancel, multiline }: {
  value: string;
  onChange: (v: string) => void;
  onCommit: () => void;
  onCancel: () => void;
  multiline: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement & HTMLInputElement>(null);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const onKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === "Escape") onCancel();
    else if (e.key === "Enter" && (!multiline || e.ctrlKey || e.metaKey)) onCommit();
  };
  const props = {
    ref,
    value,
    className: "nodrag nowheel nw-edit",
    onChange: (e: React.ChangeEvent<HTMLTextAreaElement & HTMLInputElement>) => onChange(e.target.value),
    onBlur: onCommit,
    onKeyDown,
  };
  return multiline ? <textarea {...props} /> : <input {...props} />;
}

export const TextNode = memo(({ id, data, selected }: NodeProps<CNode>) => {
  const raw = data.raw;
  const ed = useEditable(id, raw, "text");
  const { cls, svg } = look(raw, "text", true);
  return (
    <div className={cls} style={colorStyle(raw)} onDoubleClick={ed.start}>
      {svg}
      <NodeResizer isVisible={selected} minWidth={40} minHeight={30} />
      <Handles id={id} raw={raw} />
      {ed.editing ? (
        <Editor value={ed.draft} onChange={ed.setDraft} onCommit={ed.commit} onCancel={ed.cancel} multiline />
      ) : (
        <div className="nw-body">
          {raw.text ? <Markdown text={raw.text} /> : <span className="muted">Double-click to edit</span>}
        </div>
      )}
    </div>
  );
});

export const GroupNode = memo(({ id, data, selected }: NodeProps<CNode>) => {
  const raw = data.raw;
  const ed = useEditable(id, raw, "label");
  return (
    <div className={look(raw, "group").cls} style={colorStyle(raw)}>
      <NodeResizer isVisible={selected} minWidth={60} minHeight={60} />
      <Handles id={id} raw={raw} />
      <div className="nw-group-label" onDoubleClick={ed.start}>
        {ed.editing ? (
          <Editor value={ed.draft} onChange={ed.setDraft} onCommit={ed.commit} onCancel={ed.cancel} multiline={false} />
        ) : (
          raw.label || <span className="muted">Group</span>
        )}
      </div>
    </div>
  );
});

export const LinkNode = memo(({ id, data, selected }: NodeProps<CNode>) => {
  const raw = data.raw;
  const ed = useEditable(id, raw, "url");
  const href = safeUrl(raw.url ?? "");
  return (
    <div className={look(raw, "link").cls} style={colorStyle(raw)} onDoubleClick={ed.start}>
      <NodeResizer isVisible={selected} minWidth={80} minHeight={30} />
      <Handles id={id} raw={raw} />
      {ed.editing ? (
        <Editor value={ed.draft} onChange={ed.setDraft} onCommit={ed.commit} onCancel={ed.cancel} multiline={false} />
      ) : (
        <div className="nw-body">
          <div className="nw-kind">link</div>
          {href ? (
            <a className="nodrag" href={href} target="_blank" rel="noopener noreferrer">{raw.url}</a>
          ) : (
            <span>{raw.url || "(no url)"}</span>
          )}
        </div>
      )}
    </div>
  );
});

function CanvasLink({ raw }: { raw: Record<string, any> }) {
  const links = useContext(TabLinksContext);
  const target = linkTarget(String(raw.file ?? ""), links.tabs);
  const node = subpathNode(raw.subpath);
  const name = String(raw.file).slice(0, -".canvas".length);
  return (
    <div className="nw-body">
      <div className="nw-kind">tab link</div>
      {target ? (
        <button className="nodrag nw-tablink" title={node ? `Open "${target.name}" at node ${node}` : `Open "${target.name}"`}
          onClick={(e) => { e.stopPropagation(); links.open(target.id, node); }}>
          {target.id === links.current ? "↺ " : "→ "}{target.name}{node ? <span className="muted"> #{node}</span> : null}
        </button>
      ) : (
        <span className="muted" title="No tab with that name in this workspace">{name} (missing tab)</span>
      )}
    </div>
  );
}

function AttachmentView({ raw }: { raw: Record<string, any> }) {
  const a = attachmentOf(String(raw.file ?? ""))!;
  const [broken, setBroken] = useState(false);
  if (a.image && !broken) {
    return <img className="nw-image" src={a.url} alt={a.name} draggable={false} onError={() => setBroken(true)} />;
  }
  return (
    <div className="nw-body">
      <div className="nw-kind">{broken ? "missing image" : "file"}</div>
      <a className="nodrag nw-download" href={a.url} download={a.name} title={`Download ${a.name}`}>⤓ {a.name}</a>
    </div>
  );
}

export const FileNode = memo(({ id, data, selected }: NodeProps<CNode>) => {
  const raw = data.raw;
  const ed = useEditable(id, raw, "file");
  const tabLink = isCanvasFile(String(raw.file ?? ""));
  const attached = !!attachmentOf(String(raw.file ?? ""));
  return (
    <div className={look(raw, "file").cls + (tabLink ? " nw-canvaslink" : "") + (attached ? " nw-attachment" : "")}
      style={colorStyle(raw)} onDoubleClick={attached ? undefined : ed.start}>
      <NodeResizer isVisible={selected} minWidth={80} minHeight={30} />
      <Handles id={id} raw={raw} />
      {ed.editing ? (
        <Editor value={ed.draft} onChange={ed.setDraft} onCommit={ed.commit} onCancel={ed.cancel} multiline={false} />
      ) : attached ? <AttachmentView raw={raw} /> : tabLink ? <CanvasLink raw={raw} /> : (
        <div className="nw-body">
          <div className="nw-kind">file</div>
          <span>{raw.file}{raw.subpath ?? ""}</span>
        </div>
      )}
    </div>
  );
});

export const nodeTypes = { text: TextNode, group: GroupNode, link: LinkNode, file: FileNode };
