// /s/<token>: a read-only share link (design §9). Public, no sign-in; the
// token scopes every request (api/nodewright/shares.py). Same renderer as the
// editor, so shapes, line styles, tab links and attachments look the same.
import { useCallback, useEffect, useState } from "react";
import {
  applyNodeChanges, Background, BackgroundVariant, ConnectionMode, Controls, ReactFlow, ReactFlowProvider,
  useReactFlow, type NodeChange,
} from "@xyflow/react";
import type { CanvasMeta } from "./api";
import { toFlow, type CEdge, type CNode } from "./canvasMapping";
import { RoutedEdge } from "./edges";
import { Markers } from "./markers";
import { nodeTypes, ReadOnly } from "./nodes";
import { setAttachmentUrl, TabLinksContext } from "./tablinks";

const edgeTypes = { routed: RoutedEdge };
const token = decodeURIComponent(location.pathname.replace(/^\/s\//, "").split("/")[0] ?? "");
const base = `/api/s/${encodeURIComponent(token)}`;
setAttachmentUrl((id) => `${base}/attachments/${id}`);

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
  const flow = useReactFlow();
  const [nodes, setNodes] = useState(doc.nodes);
  const onNodesChange = useCallback((c: NodeChange<CNode>[]) => setNodes((n) => applyNodeChanges(c, n)), []);
  // Wait for measured sizes, then fit the view or zoom to a linked node.
  useEffect(() => {
    let live = true;
    void (async () => {
      for (let i = 0; i < 60 && live; i++) {
        if (doc.nodes.every((n) => flow.getInternalNode(n.id)?.measured.width)) break;
        await new Promise((ok) => setTimeout(ok, 50));
      }
      if (!live) return;
      if (focus && flow.getNode(focus)) void flow.fitView({ nodes: [{ id: focus }], padding: 0.5, maxZoom: 1 });
      else void flow.fitView({ padding: 0.1, maxZoom: 1 });
    })();
    return () => { live = false; };
  }, [flow, doc, focus]);
  return (
    <TabLinksContext.Provider value={{ tabs: doc.tabs, current: doc.id, open }}>
      <ReactFlow
        nodes={nodes}
        edges={doc.edges}
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        edgesReconnectable={false}
        connectionMode={ConnectionMode.Loose}
        minZoom={0.05}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <Markers edges={doc.edges} />
    </TabLinksContext.Provider>
  );
}

export default function Share() {
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
        <ReadOnly.Provider value={true}>
          <ReactFlowProvider key={doc.id}>
            <View doc={doc} focus={focus} open={open} />
          </ReactFlowProvider>
        </ReadOnly.Provider>
      </main>
    </div>
  );
}
