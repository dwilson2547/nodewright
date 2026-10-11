// Edit one node's ports (design §13.1): presets, then each port's side,
// position along it and label. Changes apply live; the node's lines follow.
import { useState } from "react";
import { nextPortId, PRESETS, SIDES, type Port, type Side } from "./ports";

export function PortsPanel({ ports, onChange, onClose }: {
  ports: Port[];
  /** `renamed` is [old id, new id] when a port's id changed, so its lines can follow. */
  onChange: (ports: Port[], renamed?: [string, string]) => void;
  onClose: () => void;
}) {
  const [preset, setPreset] = useState("");
  const set = (i: number, patch: Partial<Port>) =>
    onChange(ports.map((p, j) => {
      if (j !== i) return p;
      const next = { ...p, ...patch };
      if (!next.label) delete next.label;
      return next;
    }));
  const rename = (i: number, id: string) => {
    const clean = id.trim().slice(0, 64);
    const old = ports[i].id;
    if (!clean || clean === old || ports.some((p, j) => j !== i && p.id === clean)) return;
    onChange(ports.map((p, j) => (j === i ? { ...p, id: clean } : p)), [old, clean]);
  };

  return (
    <div className="ports-panel" onKeyDown={(e) => e.stopPropagation()}>
      <header>
        <strong>Ports</strong>
        <span className="grow" />
        <button onClick={onClose} aria-label="Close ports">×</button>
      </header>
      <div className="ports-row">
        <select value={preset} aria-label="Port preset" onChange={(e) => {
          const p = PRESETS.find((x) => (x.value || "none") === e.target.value);
          setPreset("");
          if (p && (ports.length === 0 || confirm(`Replace this node's ${ports.length} port(s) with "${p.label}"?`))) {
            onChange(p.ports());
          }
        }}>
          <option value="">Preset…</option>
          {PRESETS.map((p) => <option key={p.value || "none"} value={p.value || "none"}>{p.label}</option>)}
        </select>
        <button onClick={() => onChange([...ports, { id: nextPortId(ports), side: "right", at: 0.5 }])}>+ Port</button>
      </div>
      {ports.length === 0 ? (
        <p className="muted">No ports: the node uses its four side handles.</p>
      ) : (
        <table>
          <thead><tr><th>Id</th><th>Label</th><th>Side</th><th>Position</th><th /></tr></thead>
          <tbody>
            {ports.map((p, i) => (
              <tr key={i + ":" + p.id}>
                <td><input defaultValue={p.id} aria-label="Port id" size={6}
                  onBlur={(e) => { rename(i, e.target.value); e.target.value = ports[i]?.id ?? ""; }} /></td>
                <td><input value={p.label ?? ""} aria-label="Port label" size={8}
                  onChange={(e) => set(i, { label: e.target.value.slice(0, 100) })} /></td>
                <td>
                  <select value={p.side} aria-label="Port side" onChange={(e) => set(i, { side: e.target.value as Side })}>
                    {SIDES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
                <td><input type="range" min={0} max={1} step={0.05} value={p.at} aria-label="Position along the side"
                  title={`${Math.round(p.at * 100)}% along the ${p.side} side`}
                  onChange={(e) => set(i, { at: Number(e.target.value) })} /></td>
                <td><button onClick={() => onChange(ports.filter((_, j) => j !== i))} aria-label={`Delete port ${p.id}`}>×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
