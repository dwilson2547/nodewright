// /render?canvas=<id>&t=<ticket>[&focus=a,b]: one canvas, read-only and
// chrome-free, for the headless browser behind the render_canvas MCP tool
// (api/nodewright/render.py). Marks #nw-render[data-ready] once everything,
// images included, has been drawn and fitted.
import { useEffect, useState } from "react";
import { ConnectionMode, getNodesBounds, getViewportForBounds, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import type { CanvasMeta } from "./api";
import { toFlow, type CEdge, type CNode } from "./canvasMapping";
import { NetColours, RoutedEdge } from "./edges";
import { Markers } from "./markers";
import { nodeTypes, ReadOnly } from "./nodes";
import { setAttachmentUrl, TabLinksContext } from "./tablinks";

const edgeTypes = { routed: RoutedEdge };
const q = new URLSearchParams(location.search);
const canvasId = q.get("canvas") ?? "";
const ticket = q.get("t") ?? "";
const focus = (q.get("focus") ?? "").split(",").filter(Boolean);


type Loaded = { nodes: CNode[]; edges: CEdge[]; tabs: CanvasMeta[]; colorByNet: boolean };

function imagesSettled(timeoutMs: number): Promise<void> {
  const pending = [...document.images].filter((i) => !i.complete);
  const all = Promise.all(pending.map((i) => new Promise((ok) => {
    i.addEventListener("load", ok, { once: true });
    i.addEventListener("error", ok, { once: true });
  })));
  return Promise.race([all.then(() => undefined), new Promise<void>((ok) => setTimeout(ok, timeoutMs))]);
}

const frame = () => new Promise((ok) => requestAnimationFrame(ok));
const sleep = (ms: number) => new Promise((ok) => setTimeout(ok, ms));

function Shot({ doc }: { doc: Loaded }) {
  const flow = useReactFlow();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let live = true;
    void (async () => {
      // useNodesInitialized() never turns true for every node type, so poll
      // for measured sizes instead (3 s cap).
      for (let i = 0; i < 60; i++) {
        if (doc.nodes.every((n) => flow.getInternalNode(n.id)?.measured.width)) break;
        await sleep(50);
      }
      // Not flow.fitView(): with controlled nodes and no onNodesChange its
      // promise waits for a nodes update that never comes.
      const known = new Set(doc.nodes.map((n) => n.id));
      const only = focus.filter((id) => known.has(id));
      const nodes = flow.getNodes().filter((n) => !only.length || only.includes(n.id));
      if (nodes.length) {
        const vp = getViewportForBounds(getNodesBounds(nodes), window.innerWidth, window.innerHeight, 0.05, 1, 0.05);
        await flow.setViewport(vp);
      }
      await imagesSettled(5000);
      await frame();
      await frame();
      if (live) setReady(true);
    })();
    return () => { live = false; };
  }, [flow, doc]);
  return (
    <div id="nw-render" data-ready={ready ? "1" : undefined} style={{ width: "100vw", height: "100vh" }}>
      <ReactFlow
        nodes={doc.nodes}
        edges={doc.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        edgesReconnectable={false}
        connectionMode={ConnectionMode.Loose}
        minZoom={0.05}
        maxZoom={1}
        colorMode="light"
        proOptions={{ hideAttribution: true }}
      />
      <Markers edges={doc.edges} />
    </div>
  );
}

export default function Render() {
  // Not at module load: main.tsx imports every page (see Share.tsx).
  setAttachmentUrl((id) =>
    `/api/render/${encodeURIComponent(canvasId)}/attachments/${id}?t=${encodeURIComponent(ticket)}`);
  const [doc, setDoc] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch(`/api/render/${encodeURIComponent(canvasId)}?t=${encodeURIComponent(ticket)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => setDoc({ ...toFlow(j.data), tabs: j.tabs ?? [], colorByNet: j.data?.colorByNet === true }))
      .catch((e) => setError(String(e)));
  }, []);
  if (error) return <div id="nw-render" data-ready="error" style={{ padding: 20 }}>Couldn't load the canvas: {error}</div>;
  if (!doc) return null;
  return (
    <ReadOnly.Provider value={true}>
      <TabLinksContext.Provider value={{ tabs: doc.tabs, current: canvasId, open: () => undefined }}>
        <ReactFlowProvider>
          <NetColours.Provider value={doc.colorByNet}>
            <Shot doc={doc} />
          </NetColours.Provider>
        </ReactFlowProvider>
      </TabLinksContext.Provider>
    </ReadOnly.Provider>
  );
}
