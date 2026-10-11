// The History panel (design §14): a tab's revisions newest first, named
// versions, and the entry point to preview and restore (Editor.tsx).
// Autosave makes many small revisions, so a run of edits by one person from
// one source, each within RUN_GAP_MS of the next, shows as one row.
import { useCallback, useEffect, useState } from "react";
import { api, type Revision } from "./api";

const RUN_GAP_MS = 15 * 60 * 1000;

type Run = { key: string; revs: Revision[] };

/** Consecutive unnamed revisions by the same author and source, close in time. */
function runs(revs: Revision[]): Run[] {
  const out: Run[] = [];
  for (const r of revs) {
    const last = out[out.length - 1];
    const prev = last?.revs[last.revs.length - 1];
    const joins = prev && !r.label && !prev.label && r.source !== "restore" && prev.source !== "restore"
      && r.source === prev.source && r.by === prev.by
      && Date.parse(prev.created_at) - Date.parse(r.created_at) <= RUN_GAP_MS;
    if (joins) last.revs.push(r);
    else out.push({ key: String(r.revision), revs: [r] });
  }
  return out;
}

export function when(iso: string): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return time;
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: sameYear ? undefined : "numeric" }) + " " + time;
}

function origin(r: Revision): string {
  if (r.source === "mcp") return "🤖 agent";
  if (r.source === "import") return "import";
  if (r.source === "restore") return `restored r${r.restored_from}`;
  return "";
}

type Props = {
  canvasId: string;
  /** The tab's current revision; the list reloads when it moves. */
  head: number;
  canEdit: boolean;
  previewing: number | null;
  onPreview: (rev: number) => void;
  onSaveVersion: () => Promise<void>;
  onClose: () => void;
};

export function HistoryPanel({ canvasId, head, canEdit, previewing, onPreview, onSaveVersion, onClose }: Props) {
  const [revs, setRevs] = useState<Revision[]>([]);
  const [more, setMore] = useState(false);
  const [named, setNamed] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const h = await api.history(canvasId, { named });
      setRevs(h.revisions);
      setMore(h.more);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [canvasId, named]);

  useEffect(() => {
    void load();
  }, [load, head]);

  const older = async () => {
    const h = await api.history(canvasId, { named, before: revs[revs.length - 1]?.revision });
    setRevs((rs) => [...rs, ...h.revisions]);
    setMore(h.more);
  };

  const rename = async (r: Revision) => {
    const label = prompt(r.label ? "Rename this version (empty to unname it)" : `Name revision ${r.revision}`, r.label ?? "");
    if (label === null) return;
    try {
      const out = await api.nameRevision(canvasId, r.revision, label.trim() || null);
      setRevs((rs) => (named && !out.label ? rs.filter((x) => x.revision !== r.revision)
        : rs.map((x) => (x.revision === r.revision ? out : x))));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const row = (r: Revision) => (
    <div key={r.revision} className={"hist-row" + (r.label ? " named" : "") + (previewing === r.revision ? " on" : "")}>
      <button className="hist-main" onClick={() => onPreview(r.revision)}
        title={r.revision === head ? "The current version" : "Preview this version"}>
        {r.label && <span className="hist-label">{r.label}</span>}
        <span className="hist-meta">
          {when(r.created_at)}{r.by ? ` · ${r.by}` : ""}
          {origin(r) && <span className="hist-src"> · {origin(r)}</span>}
        </span>
      </button>
      <span className="hist-rev">{r.revision === head ? "now" : `r${r.revision}`}</span>
      {canEdit && (
        <button className="tab-x" onClick={() => void rename(r)} title={r.label ? "Rename or unname" : "Name this version"}>✎</button>
      )}
    </div>
  );

  return (
    <aside className="history">
      <div className="palette-head">
        <strong>History</strong>
        <button className="tab-x" onClick={onClose} title="Close">×</button>
      </div>
      {canEdit && (
        <button className="palette-save" onClick={() => void onSaveVersion().then(load)}
          title="Name the current state so you can find and restore it later">Save version…</button>
      )}
      <label className="check hist-filter">
        <input type="checkbox" checked={named} onChange={(e) => setNamed(e.target.checked)} /> Named versions only
      </label>
      {error && <div className="palette-error" onClick={() => setError(null)}>{error}</div>}
      {revs.length === 0 && !error && (
        <p className="muted small">{named ? "No named versions yet." : "No saved changes yet."}</p>
      )}
      {runs(revs).map((run) => {
        const [top, ...rest] = run.revs;
        if (rest.length === 0) return row(top);
        const expanded = open.has(run.key);
        const toggle = (
          <button className="hist-more" onClick={() => {
            setOpen((s) => {
              const n = new Set(s);
              if (!n.delete(run.key)) n.add(run.key);
              return n;
            });
          }} title={expanded ? "Collapse" : "Show each save"}>
            {expanded ? "▾" : "▸"} {run.revs.length} saves
          </button>
        );
        return (
          <div key={run.key} className="hist-run">
            {row(top)}
            {toggle}
            {expanded && <div className="hist-sub">{rest.map((r) => row(r))}</div>}
          </div>
        );
      })}
      {more && <button className="palette-save" onClick={() => void older()}>Older…</button>}
    </aside>
  );
}
