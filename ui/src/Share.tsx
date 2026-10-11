// /s/<token>: a read-only share link (design §9). Public, no sign-in; the
// token scopes every request (api/nodewright/shares.py). Same renderer as the
// editor, so shapes, line styles, tab links and attachments look the same.
import { useCallback, useEffect, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import type { CanvasMeta } from "./api";
import { toFlow, type CEdge, type CNode } from "./canvasMapping";
import { ReadOnlyFlow } from "./ReadOnlyFlow";
import { setAttachmentUrl, TabLinksContext } from "./tablinks";
const token = decodeURIComponent(location.pathname.replace(/^\/s\//, "").split("/")[0] ?? "");
const base = `/api/s/${encodeURIComponent(token)}`;

type Shared = { id: string; name: string; workspace: string; tabs: CanvasMeta[]; nodes: CNode[]; edges: CEdge[] };

async function load(canvasId?: string): Promise<Shared> {
  const r = await fetch(canvasId ? `${base}/canvases/${encodeURIComponent(canvasId)}` : base);
  if (!r.ok) {
    const detail = await r.json().then((j: { detail?: string }) => j.detail, () => undefined);
    throw new Error(detail ?? `HTTP ${r.status}`);
  }
  const j = await r.json();
  return { ...j, ...toFlow(j.data) };
}

function View({ doc, focus, open }: { doc: Shared; focus?: string; open: (id: string, node?: string) => void }) {
  return (
    <TabLinksContext.Provider value={{ tabs: doc.tabs, current: doc.id, open }}>
      <ReadOnlyFlow nodes={doc.nodes} edges={doc.edges} focus={focus} />
    </TabLinksContext.Provider>
  );
}

export default function Share() {
  // Here, not at module load: main.tsx imports every page, so a module-level
  // call would also redirect the editor's attachments.
  setAttachmentUrl((id) => `${base}/attachments/${id}`);
  const [doc, setDoc] = useState<Shared | null>(null);
  const [focus, setFocus] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const open = useCallback((id: string, node?: string) => {
    load(id).then((d) => { setFocus(node); setDoc(d); }, (e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    load().then(setDoc, (e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    if (doc) document.title = `${doc.name} · nodewright`;
  }, [doc]);
  if (error) {
    return (
      <div className="share-error">
        <h2>Can't show this diagram</h2>
        <p>{error}</p>
        <a href="/">nodewright</a>
      </div>
    );
  }
  if (!doc) return null;
  return (
    <div className="app share">
      <header>
        <a className="brand" href="/">nodewright</a>
        <span className="ws-name">{doc.workspace}</span>
        <span className="muted">read-only</span>
      </header>
      {doc.tabs.length > 1 && (
        <nav className="tabs">
          {doc.tabs.map((t) => (
            <button key={t.id} className={"tab" + (t.id === doc.id ? " active" : "")}
              onClick={() => t.id !== doc.id && open(t.id)}>{t.name}</button>
          ))}
        </nav>
      )}
      <main>
        <ReactFlowProvider key={doc.id}>
          <View doc={doc} focus={focus} open={open} />
        </ReactFlowProvider>
      </main>
    </div>
  );
}
