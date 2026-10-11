// Read-only share links for the open tab (design §9): create, copy, revoke.
import { useEffect, useState } from "react";
import { api, type ShareLink } from "./api";

export function ShareDialog({ canvasId, canvasName, onClose }: {
  canvasId: string;
  canvasName: string;
  onClose: () => void;
}) {
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [allTabs, setAllTabs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  useEffect(() => {
    api.shares(canvasId).then(setLinks, fail);
  }, [canvasId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = (l: ShareLink) => void navigator.clipboard.writeText(l.url).then(() => {
    setCopied(l.id);
    setTimeout(() => setCopied(null), 1500);
  });
  const create = async () => {
    const l = await api.createShare(canvasId, allTabs).catch(fail);
    if (l) {
      setLinks((ls) => [...(ls ?? []), l]);
      copy(l);
    }
  };
  const revoke = async (l: ShareLink) => {
    if (!confirm("Revoke this link? Anyone using it loses access straight away.")) return;
    await api.revokeShare(l.id).then(() => setLinks((ls) => (ls ?? []).filter((x) => x.id !== l.id)), fail);
  };

  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="Share" style={{ width: "min(600px, 94vw)" }}>
        <header className="modal-head">
          <h2>Share “{canvasName}”</h2>
          <span className="grow" />
          <button onClick={onClose} aria-label="Close">×</button>
        </header>
        <p className="muted">
          Anyone with a link can view this diagram without signing in, and always sees the latest version.
          They can't edit it. Revoke a link to cut it off.
        </p>
        {error && <p className="error">{error}</p>}
        {links && (links.length ? (
          <ul className="share-list">
            {links.map((l) => (
              <li key={l.id}>
                <input readOnly value={l.url} aria-label="Share link" onFocus={(e) => e.target.select()} />
                <span className="muted" title={l.all_tabs ? "Viewers can open every tab in this workspace" : undefined}>
                  {l.all_tabs ? "all tabs" : "this tab"}
                </span>
                <button onClick={() => copy(l)}>{copied === l.id ? "Copied" : "Copy"}</button>
                <a className="button" href={l.url} target="_blank" rel="noreferrer">Open</a>
                <button onClick={() => void revoke(l)}>Revoke</button>
              </li>
            ))}
          </ul>
        ) : <p>No links yet.</p>)}
        <p>
          <label>
            <input type="checkbox" checked={allTabs} onChange={(e) => setAllTabs(e.target.checked)} />{" "}
            Include the workspace's other tabs (so tab links work)
          </label>
        </p>
        <button onClick={() => void create()}>Create link</button>
      </div>
    </div>
  );
}
