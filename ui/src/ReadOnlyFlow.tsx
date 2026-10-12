// A read-only drawing of a document: share links (Share.tsx) and the
// History panel's preview. Same renderer as the editor; place it inside a
// ReactFlowProvider (and a TabLinksContext, for tab links to open).
import { useCallback, useEffect, useState } from "react";
import {
  applyNodeChanges, Background, BackgroundVariant, ConnectionMode, Controls, ReactFlow,
  useReactFlow, type NodeChange,
} from "@xyflow/react";
import type { CEdge, CNode } from "./canvasMapping";
import { NetColours, RoutedEdge } from "./edges";
import { Markers } from "./markers";
import { nodeTypes, ReadOnly } from "./nodes";

const edgeTypes = { routed: RoutedEdge };

type Props = {
  nodes: CNode[]; edges: CEdge[]; focus?: string; colorMode?: "light" | "system";
  /** The document's colorByNet (wires.ts). */
  colorByNet?: boolean;
};

export function ReadOnlyFlow({ nodes: initial, edges, focus, colorMode = "light", colorByNet = false }: Props) {
  const flow = useReactFlow();
  // Seeded once: give each document its own ReactFlowProvider key.
  const [nodes, setNodes] = useState(initial);
  const onNodesChange = useCallback((c: NodeChange<CNode>[]) => setNodes((n) => applyNodeChanges(c, n)), []);
  // Wait for measured sizes, then fit the view or zoom to a linked node.
  useEffect(() => {
    let live = true;
    void (async () => {
      for (let i = 0; i < 60 && live; i++) {
        if (initial.every((n) => flow.getInternalNode(n.id)?.measured.width)) break;
        await new Promise((ok) => setTimeout(ok, 50));
      }
      if (!live) return;
      if (focus && flow.getNode(focus)) void flow.fitView({ nodes: [{ id: focus }], padding: 0.5, maxZoom: 1 });
      else void flow.fitView({ padding: 0.1, maxZoom: 1 });
    })();
    return () => { live = false; };
  }, [flow, initial, focus]);
  return (
    <ReadOnly.Provider value={true}>
    <NetColours.Provider value={colorByNet}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
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
        colorMode={colorMode}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <Markers edges={edges} />
    </NetColours.Provider>
    </ReadOnly.Provider>
  );
}
