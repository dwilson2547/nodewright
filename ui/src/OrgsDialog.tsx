// Organisations (design §19): the orgs you're in, their people and roles.
// Anyone can create an org; admins add people by username, change roles and
// remove people; anyone can leave. Memberships from an authentik group are
// shown but only change in authentik.
import { useEffect, useState } from "react";
import { api, type Org, type OrgMember, type OrgMembers, type OrgRole } from "./api";

const ROLE_HELP: Record<OrgRole, string> = {
  admin: "Owns every org workspace and manages the org's people",
  member: "Gets each org workspace's org access (editor unless an admin changes it)",
};

function People({ org, me, fail, onChanged }: {
  org: Org;
  me: string;
  fail: (e: unknown) => void;
  onChanged: () => void;
}) {
  const [data, setData] = useState<OrgMembers | null>(null);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<OrgRole>("member");

  useEffect(() => {
    api.orgMembers(org.id).then(setData, fail);
  }, [org.id]);

  const replace = (m: OrgMember) => setData((d) => d && {
    ...d, members: d.members.some((x) => x.user_id === m.user_id)
      ? d.members.map((x) => (x.user_id === m.user_id ? m : x))
      : [...d.members, m],
  });
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = username.trim();
    if (!name) return;
    const m = await api.addOrgMember(org.id, name, role).catch(fail);
    if (m) {
      replace(m);
      setUsername("");
    }
  };
  const setMemberRole = async (m: OrgMember, r: OrgRole) => {
    const updated = await api.setOrgRole(org.id, m.user_id, r).catch(fail);
    if (updated) {
      replace(updated);
      if (m.username === me) onChanged();
    }
  };
  const remove = async (m: OrgMember) => {
    const self = m.username === me;
    const ask = self
      ? `Leave ${org.name}? You keep any of its workspaces you were added to by name.`
      : `Remove ${m.username} from ${org.name}? They keep any of its workspaces they were added to by name.`;
    if (!confirm(ask)) return;
    await api.removeOrgMember(org.id, m.user_id).then(() => {
      if (self) onChanged();
      else setData((d) => d && { ...d, members: d.members.filter((x) => x.user_id !== m.user_id) });
    }, fail);
  };

  if (!data) return null;
  return (
    <>
      <ul className="share-list member-list">
        {data.members.map((m) => (
          <li key={m.user_id}>
            <span className="grow">
              {m.username}{m.username === me && <span className="muted"> (you)</span>}
              {m.source === "authentik" && <span className="muted" title="Comes from an authentik group; change it there"> · authentik</span>}
            </span>
            {data.can_manage && m.source === "manual" ? (
              <select value={m.role} aria-label={`Role for ${m.username}`}
                onChange={(e) => void setMemberRole(m, e.target.value as OrgRole)}>
                {data.roles.map((r) => <option key={r} value={r} title={ROLE_HELP[r]}>{r}</option>)}
              </select>
            ) : <span className="muted" title={ROLE_HELP[m.role]}>{m.role}</span>}
            {m.source === "manual" && (data.can_manage || m.username === me) && (
              <button onClick={() => void remove(m)}>{m.username === me ? "Leave" : "Remove"}</button>
            )}
          </li>
        ))}
      </ul>
      {data.can_manage && (
        <form className="member-add" onSubmit={(e) => void add(e)}>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username"
            aria-label="Username to add" autoComplete="off" />
          <select value={role} onChange={(e) => setRole(e.target.value as OrgRole)} aria-label="Role">
            {data.roles.map((r) => <option key={r} value={r} title={ROLE_HELP[r]}>{r}</option>)}
          </select>
          <button type="submit" disabled={!username.trim()}>Add</button>
        </form>
      )}
    </>
  );
}

export function OrgsDialog({ me, onClose, onChanged }: {
  me: string;
  onClose: () => void;
  /** Orgs or your place in them changed: reload the workspace list. */
  onChanged: () => void;
}) {
  const [orgs, setOrgs] = useState<Org[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  const load = () => api.orgs().then((r) => {
    setOrgs(r.orgs);
    setOpen((o) => (o && r.orgs.some((x) => x.id === o) ? o : r.orgs[0]?.id ?? null));
  }, fail);
  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const changed = () => {
    void load();
    onChanged();
  };
  const create = async () => {
    const name = prompt("Name for the new organisation")?.trim();
    if (!name) return;
    const o = await api.createOrg(name).catch(fail);
    if (o) {
      setOrgs((os) => [...(os ?? []), o].sort((a, b) => a.name.localeCompare(b.name)));
      setOpen(o.id);
      onChanged();
    }
  };
  const rename = async (o: Org) => {
    const name = prompt("Rename organisation", o.name)?.trim();
    if (!name || name === o.name) return;
    await api.renameOrg(o.id, name).then(changed, fail);
  };
  const remove = async (o: Org) => {
    if (!confirm(`Delete ${o.name}? Only possible once it owns no workspaces.`)) return;
    await api.deleteOrg(o.id).then(changed, fail);
  };

  const current = orgs?.find((o) => o.id === open);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="Organisations" style={{ width: "min(640px, 94vw)" }}>
        <header className="modal-head">
          <h2>Organisations</h2>
          <span className="grow" />
          <button onClick={onClose} aria-label="Close">×</button>
        </header>
        {error && <p className="error" onClick={() => setError(null)}>{error}</p>}
        <p className="muted">
          An organisation owns workspaces together. Its admins can do anything with them; members get the
          role each workspace gives the org. Create one, then make or move workspaces into it (Share → Move).
        </p>
        {orgs && (
          <div className="org-pick">
            {orgs.map((o) => (
              <button key={o.id} aria-pressed={o.id === open} onClick={() => setOpen(o.id)}>
                {o.name} <span className="muted">{o.role}</span>
              </button>
            ))}
            <button onClick={() => void create()}>+ New organisation</button>
          </div>
        )}
        {orgs?.length === 0 && <p>You're not in any organisation yet.</p>}
        {current && (
          <section key={current.id}>
            <h3 className="org-title">
              {current.name}
              {current.role === "admin" && (
                <>
                  {" "}
                  <button onClick={() => void rename(current)} disabled={current.managed}
                    title={current.managed ? "Named in the server's authentik group mapping" : "Rename"}>Rename</button>
                  {" "}
                  <button onClick={() => void remove(current)}>Delete</button>
                </>
              )}
            </h3>
            <People org={current} me={me} fail={fail} onChanged={changed} />
            {current.role === "admin" && <p className="muted">They need to have signed in to nodewright once.</p>}
          </section>
        )}
      </div>
    </div>
  );
}
