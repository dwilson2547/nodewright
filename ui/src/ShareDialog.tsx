// Sharing (design §9, §11.1): workspace members, then read-only links for the open tab.
// Owners manage both; members see who else has access and can leave.
import { useEffect, useState } from "react";
import { api, type Member, type Members, type Role, type ShareLink, type Workspace } from "./api";

const ROLE_HELP: Record<Role, string> = {
  owner: "Owns the workspace",
  editor: "Can add, edit and delete tabs",
  viewer: "Can open tabs but not change them",
};

function People({ ws, me, fail, onLeft }: {
  ws: Workspace;
  me: string;
  fail: (e: unknown) => void;
  onLeft: () => void;
}) {
  const [data, setData] = useState<Members | null>(null);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<Role>("editor");

  useEffect(() => {
    api.members(ws.id).then(setData, fail);
  }, [ws.id]);

  const replace = (m: Member) => setData((d) => d && {
    ...d, members: d.members.some((x) => x.user_id === m.user_id)
      ? d.members.map((x) => (x.user_id === m.user_id ? m : x))
      : [...d.members, m],
  });
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = username.trim();
    if (!name) return;
    const m = await api.addMember(ws.id, name, role).catch(fail);
    if (m) {
      replace(m);
      setUsername("");
    }
  };
  const setMemberRole = async (m: Member, r: Role) => {
    const updated = await api.setMemberRole(ws.id, m.user_id, r).catch(fail);
    if (updated) replace(updated);
  };
  const remove = async (m: Member) => {
    const self = m.username === me;
    const ask = self
      ? `Leave "${ws.name}"? You'll lose access until the owner adds you again.`
      : `Remove ${m.username} from "${ws.name}"?`;
    if (!confirm(ask)) return;
    await api.removeMember(ws.id, m.user_id).then(() => {
      if (self) onLeft();
      else setData((d) => d && { ...d, members: d.members.filter((x) => x.user_id !== m.user_id) });
    }, fail);
  };

  if (!data) return null;
  return (
    <section>
      <h3>People</h3>
      <p className="muted">Members see “{ws.name}” in their own sidebar, with every tab in it.</p>
      <ul className="share-list member-list">
        {data.members.map((m) => (
          <li key={m.user_id}>
            <span className="grow">{m.username}{m.username === me && <span className="muted"> (you)</span>}</span>
            {data.can_manage && m.role !== "owner" ? (
              <select value={m.role} aria-label={`Role for ${m.username}`}
                onChange={(e) => void setMemberRole(m, e.target.value as Role)}>
                {data.assignable.map((r) => <option key={r} value={r} title={ROLE_HELP[r]}>{r}</option>)}
              </select>
            ) : <span className="muted" title={ROLE_HELP[m.role]}>{m.role}</span>}
            {m.role !== "owner" && (data.can_manage || m.username === me) && (
              <button onClick={() => void remove(m)}>{m.username === me ? "Leave" : "Remove"}</button>
            )}
          </li>
        ))}
      </ul>
      {data.can_manage && (
        <form className="member-add" onSubmit={(e) => void add(e)}>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username"
            aria-label="Username to add" autoComplete="off" />
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="Role">
            {data.assignable.map((r) => <option key={r} value={r} title={ROLE_HELP[r]}>{r}</option>)}
          </select>
          <button type="submit" disabled={!username.trim()}>Add</button>
        </form>
      )}
      {data.can_manage && (
        <p className="muted">They need to have signed in to nodewright once.</p>
      )}
    </section>
  );
}

function Links({ canvasId, canvasName, fail }: {
  canvasId: string;
  canvasName: string;
  fail: (e: unknown) => void;
}) {
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [allTabs, setAllTabs] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    api.shares(canvasId).then(setLinks, fail);
  }, [canvasId]);

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
    <section>
      <h3>Read-only links to “{canvasName}”</h3>
      <p className="muted">
        Anyone with a link can view this diagram without signing in, and always sees the latest version.
        They can't edit it. Revoke a link to cut it off.
      </p>
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
    </section>
  );
}

export function ShareDialog({ workspace, canvasId, canvasName, me, onClose, onLeft }: {
  workspace: Workspace;
  canvasId: string | null;
  canvasName: string;
  me: string;
  onClose: () => void;
  onLeft: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="Share" style={{ width: "min(600px, 94vw)" }}>
        <header className="modal-head">
          <h2>Share “{workspace.name}”</h2>
          <span className="grow" />
          <button onClick={onClose} aria-label="Close">×</button>
        </header>
        {error && <p className="error">{error}</p>}
        <People ws={workspace} me={me} fail={fail} onLeft={onLeft} />
        {workspace.role === "owner" && canvasId && <Links canvasId={canvasId} canvasName={canvasName} fail={fail} />}
      </div>
    </div>
  );
}
