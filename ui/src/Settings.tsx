import { useEffect, useState } from "react";
import { api, type NewToken, type Token } from "./api";

function snippets(t: NewToken) {
  const header = `Authorization: Bearer ${t.token}`;
  return {
    claude: `claude mcp add --transport http nodewright ${t.mcp_url} --header "${header}"`,
    json: JSON.stringify(
      { mcpServers: { nodewright: { type: "http", url: t.mcp_url, headers: { Authorization: `Bearer ${t.token}` } } } },
      null,
      2,
    ),
  };
}

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button onClick={() => void navigator.clipboard.writeText(text).then(() => {
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    })}>{done ? "Copied" : "Copy"}</button>
  );
}

function Tokens() {
  const [tokens, setTokens] = useState<Token[] | null>(null);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<NewToken | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
  const load = () => api.tokens().then(setTokens, fail);
  useEffect(() => {
    void load();
  }, []);

  const create = async () => {
    setError(null);
    try {
      const t = await api.createToken(name.trim() || "agent");
      setCreated(t);
      setName("");
      await load();
    } catch (e) {
      fail(e);
    }
  };

  const revoke = async (t: Token) => {
    if (!confirm(`Revoke "${t.name}"? Agents using it stop working immediately.`)) return;
    await api.revokeToken(t.id).catch(fail);
    if (created?.id === t.id) setCreated(null);
    await load();
  };

  const s = created && snippets(created);
  return (
    <section>
      <h3>Access tokens</h3>
      <p className="muted">
        An agent connects to nodewright's MCP server with a token and edits your canvases as you.
        Tokens only work for MCP, not for signing in here.
      </p>
      {error && <p className="error">{error}</p>}
      <form className="row" onSubmit={(e) => { e.preventDefault(); void create(); }}>
        <input placeholder="Name, e.g. laptop – Claude Code" value={name} maxLength={100}
          onChange={(e) => setName(e.target.value)} aria-label="Token name" />
        <button type="submit" className="primary">Create token</button>
      </form>
      {created && s && (
        <div className="token-once">
          <p><strong>Copy this token now — it won't be shown again.</strong></p>
          <div className="row"><code className="grow">{created.token}</code><Copy text={created.token} /></div>
          <p className="muted">Claude Code:</p>
          <div className="row"><pre className="grow">{s.claude}</pre><Copy text={s.claude} /></div>
          <p className="muted">Copilot CLI (<code>~/.copilot/mcp-config.json</code>) and other clients that take an <code>mcpServers</code> block:</p>
          <div className="row"><pre className="grow">{s.json}</pre><Copy text={s.json} /></div>
        </div>
      )}
      {tokens && tokens.length > 0 && (
        <table className="tokens">
          <thead><tr><th>Name</th><th>Token</th><th>Created</th><th>Last used</th><th /></tr></thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td><code>{t.prefix}…</code></td>
                <td>{new Date(t.created_at).toLocaleDateString()}</td>
                <td>{t.last_used_at ? new Date(t.last_used_at).toLocaleString() : "never"}</td>
                <td><button onClick={() => void revoke(t)}>Revoke</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {tokens && tokens.length === 0 && <p className="muted">No tokens yet.</p>}
    </section>
  );
}

function StyleGuideEditor() {
  const [text, setText] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const [isDefault, setIsDefault] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.styleGuide().then((g) => {
      setText(g.text);
      setSaved(g.text);
      setIsDefault(g.is_default);
    }, (e) => setError(String(e.message || e)));
  }, []);

  const put = async (value: string) => {
    setError(null);
    try {
      const g = await api.saveStyleGuide(value);
      setText(g.text);
      setSaved(g.text);
      setIsDefault(g.is_default);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section>
      <h3>Style guide for agents</h3>
      <p className="muted">
        Agents read this before drawing. Describe how you like diagrams: direction, colours and
        what they mean, how much text per node, naming. Markdown is fine.
        {isDefault && " You're seeing the built-in default."}
      </p>
      {error && <p className="error">{error}</p>}
      {text !== null && (
        <>
          <textarea className="styleguide" value={text} maxLength={20000} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button className="primary" disabled={text === saved && !isDefault} onClick={() => void put(text)}>Save</button>
            <button disabled={isDefault} onClick={() => void put("")}>Reset to default</button>
          </div>
        </>
      )}
    </section>
  );
}

export function AgentSettings({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="Agents">
        <header className="modal-head">
          <h2>Agents</h2>
          <span className="grow" />
          <button onClick={onClose} aria-label="Close">×</button>
        </header>
        <Tokens />
        <StyleGuideEditor />
      </div>
    </div>
  );
}
