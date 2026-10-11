import { memo, useEffect, useRef, useState, type CSSProperties } from "react";
import { Handle, NodeResizer, Position, useReactFlow, type NodeProps } from "@xyflow/react";
import { resolveColor, type CNode } from "./canvasMapping";
import { Markdown, safeUrl } from "./markdown";

const SIDES: [string, Position][] = [
  ["top", Position.Top],
  ["right", Position.Right],
  ["bottom", Position.Bottom],
  ["left", Position.Left],
];

// Every side is a "source" handle; the flow runs in ConnectionMode.Loose, so
// any side can connect to any side, as in JSON Canvas.
function Handles() {
  return (
    <>
      {SIDES.map(([id, pos]) => (
        <Handle key={id} id={id} type="source" position={pos} className="nw-handle" />
      ))}
    </>
  );
}

function colorStyle(raw: Record<string, any>): CSSProperties {
  const c = resolveColor(raw.color);
  return c ? ({ "--node-color": c } as CSSProperties) : {};
}

function useEditable(id: string, raw: Record<string, any>, field: string) {
  const { updateNodeData } = useReactFlow();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const start = () => {
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
  return (
    <div className="nw-node nw-text" style={colorStyle(raw)} onDoubleClick={ed.start}>
      <NodeResizer isVisible={selected} minWidth={40} minHeight={30} />
      <Handles />
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
    <div className="nw-node nw-group" style={colorStyle(raw)}>
      <NodeResizer isVisible={selected} minWidth={60} minHeight={60} />
      <Handles />
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
    <div className="nw-node nw-link" style={colorStyle(raw)} onDoubleClick={ed.start}>
      <NodeResizer isVisible={selected} minWidth={80} minHeight={30} />
      <Handles />
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

export const FileNode = memo(({ id, data, selected }: NodeProps<CNode>) => {
  const raw = data.raw;
  const ed = useEditable(id, raw, "file");
  return (
    <div className="nw-node nw-file" style={colorStyle(raw)} onDoubleClick={ed.start}>
      <NodeResizer isVisible={selected} minWidth={80} minHeight={30} />
      <Handles />
      {ed.editing ? (
        <Editor value={ed.draft} onChange={ed.setDraft} onCommit={ed.commit} onCancel={ed.cancel} multiline={false} />
      ) : (
        <div className="nw-body">
          <div className="nw-kind">file</div>
          <span>{raw.file}{raw.subpath ?? ""}</span>
        </div>
      )}
    </div>
  );
});

export const nodeTypes = { text: TextNode, group: GroupNode, link: LinkNode, file: FileNode };
