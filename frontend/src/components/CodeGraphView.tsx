"use client";

import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  Position,
  BackgroundVariant,
} from "reactflow";
import "reactflow/dist/style.css";
import type { GraphNode, GraphEdge } from "@/lib/api";

const TYPE_COLORS: Record<string, string> = {
  function: "#5eead4",
  method: "#60a5fa",
  class: "#c084fc",
  interface: "#fbbf24",
  variable: "#64748b",
  module: "#34d399",
  endpoint: "#f87171",
  import: "#94a3b8",
};

interface CodeGraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function CodeGraphView({ nodes, edges }: CodeGraphViewProps) {
  const { flowNodes, flowEdges } = useMemo(() => {
    // Position nodes in a circle
    const radius = Math.max(100, Math.min(250, nodes.length * 5));
    const fnodes: Node[] = nodes.map((node, i) => {
      const angle = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
      return {
        id: node.id,
        data: {
          label: (
            <div className="flex flex-col items-center gap-1">
              <span className="text-xs font-medium text-white">{node.label}</span>
              <span className="text-[10px] text-slate-400">{node.type}</span>
            </div>
          ),
        },
        position: {
          x: Math.cos(angle) * radius + 200,
          y: Math.sin(angle) * radius + 200,
        },
        style: {
          background: "#0c0f14",
          border: `1px solid ${TYPE_COLORS[node.type] || "#1a1f28"}`,
          borderRadius: "6px",
          padding: "4px 8px",
          fontSize: "11px",
          width: "auto",
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      };
    });

    const fedges: Edge[] = edges.map((edge, i) => ({
      id: `e-${i}`,
      source: edge.source,
      target: edge.target,
      animated: edge.certainty === "inferred",
      style: {
        stroke: edge.relation_type === "imports" ? "#60a5fa" : "#2dd4bf",
        strokeWidth: 1,
        opacity: edge.certainty === "unknown" ? 0.3 : 0.6,
      },
    }));

    return { flowNodes: fnodes, flowEdges: fedges };
  }, [nodes, edges]);

  return (
    <div className="h-full w-full rounded-md overflow-hidden bg-prism-bg/50">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        fitView
        attributionPosition="bottom-left"
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#1a1f28" />
        <Controls
          showInteractive={false}
          style={{
            background: "#0c0f14",
            borderColor: "#1a1f28",
          }}
        />
        <MiniMap
          nodeColor={(n) => {
            const type = n.data?.label?.props?.children?.[1]?.props?.children;
            return TYPE_COLORS[type] || "#5eead4";
          }}
          maskColor="rgba(7, 9, 12, 0.8)"
          style={{
            background: "#0c0f14",
          }}
        />
      </ReactFlow>
    </div>
  );
}
