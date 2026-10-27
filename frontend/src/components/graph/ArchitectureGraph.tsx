"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  type EdgeChange,
  type OnSelectionChangeParams,
  applyNodeChanges,
  applyEdgeChanges,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";

import { api } from "@/lib/api";
import type { ArchGraphData, GraphLevel } from "@/lib/graphTypes";
import { NODE_TYPE_META, EDGE_TYPE_META } from "@/lib/graphTypes";
import { GraphNodeComponent, type GraphNodeData } from "./GraphNodeComponent";
import { GraphEdgeComponent } from "./GraphEdgeComponent";
import { NodeDetailsPanel } from "./NodeDetailsPanel";
import { GraphSearch } from "./GraphSearch";
import { GraphLegend } from "./GraphLegend";
import {
  Loader2,
  AlertTriangle,
  Layers,
  FileCode,
  Braces,
  RefreshCw,
  Maximize2,
  ShieldAlert,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── React Flow node/edge type maps ─────────────────────────

const NODE_TYPES = { custom: GraphNodeComponent };
const EDGE_TYPES = { custom: GraphEdgeComponent };

// ── Dagre layout ───────────────────────────────────────────

async function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  level: string,
): Promise<Node[]> {
  // Dynamic import so it doesn't bloat SSR
  const dagre = await import("dagre").then((m) => m.default ?? m);
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));

  // Use TB (top-to-bottom) for file and symbol levels so nodes stack
  // vertically instead of spreading in one long horizontal line.
  // LR (left-to-right) is fine for module level (usually 2-3 modules).
  const rankdir = level === "module" ? "LR" : "TB";
  const ranksep = level === "module" ? 80 : 60;
  const nodesep = level === "module" ? 40 : 25;

  g.setGraph({ rankdir, ranksep, nodesep, edgesep: 15, marginx: 20, marginy: 20 });

  nodes.forEach((n) => g.setNode(n.id, { width: 180, height: 52 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 90, y: pos.y - 26 } };
  });
}

// ── Level config ───────────────────────────────────────────

const LEVELS: { id: GraphLevel; label: string; icon: React.ReactNode; description: string }[] = [
  {
    id: "module",
    label: "Modules",
    icon: <Layers className="h-3.5 w-3.5" />,
    description: "Grouped by directory — high-level architecture",
  },
  {
    id: "file",
    label: "Files",
    icon: <FileCode className="h-3.5 w-3.5" />,
    description: "Individual source files and their imports",
  },
  {
    id: "symbol",
    label: "Symbols",
    icon: <Braces className="h-3.5 w-3.5" />,
    description: "Functions, classes and direct call relationships",
  },
];

// ── Main component ─────────────────────────────────────────

interface ArchitectureGraphProps {
  repoId: string;
  className?: string;
}

export function ArchitectureGraph({ repoId, className }: ArchitectureGraphProps) {
  return (
    <ReactFlowProvider>
      <ArchitectureGraphInner repoId={repoId} className={className} />
    </ReactFlowProvider>
  );
}

function ArchitectureGraphInner({ repoId, className }: ArchitectureGraphProps) {
  const { fitView } = useReactFlow();

  const [level, setLevel] = useState<GraphLevel>("module");
  const [graphData, setGraphData] = useState<ArchGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set());
  const [highlightedEdgeIds, setHighlightedEdgeIds] = useState<Set<string>>(new Set());
  const [showDeadCode, setShowDeadCode] = useState(true);

  const hasLayout = useRef(false);

  // ── Fetch graph data ──────────────────────────────────────

  const fetchGraph = useCallback(
    async (lvl: GraphLevel) => {
      setLoading(true);
      setError(null);
      setSelectedNodeId(null);
      setHighlightedNodeIds(new Set());
      setHighlightedEdgeIds(new Set());
      hasLayout.current = false;
      try {
        const data = await api.getArchitectureGraph(repoId, lvl, 300);
        setGraphData(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load graph");
      } finally {
        setLoading(false);
      }
    },
    [repoId],
  );

  useEffect(() => {
    fetchGraph(level);
  }, [level, fetchGraph]);

  // ── Convert API data → React Flow nodes+edges ─────────────

  useEffect(() => {
    if (!graphData) return;

    const rfNodes: Node<GraphNodeData>[] = graphData.nodes.map((n, i) => ({
      id: n.id,
      type: "custom",
      position: { x: (i % 8) * 220, y: Math.floor(i / 8) * 80 }, // initial grid
      data: {
        ...n,
        dimmed: false,
        changed: false,
        selected: false,
        is_possibly_dead: n.is_possibly_dead ?? false,
      },
      // Hide dead code nodes when toggle is off
      hidden: !showDeadCode && (n.is_possibly_dead ?? false),
    }));

    const rfEdges: Edge[] = graphData.edges.map((e) => {
      const meta = EDGE_TYPE_META[e.relation_type as keyof typeof EDGE_TYPE_META] ?? EDGE_TYPE_META["references"];
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        type: "custom",
        data: {
          relation_type: e.relation_type,
          evidence_class: e.evidence_class,
          line_number: e.line_number,
          source_file: e.source_file,
          target_file: e.target_file,
          source_symbol: e.source_symbol,
          target_symbol: e.target_symbol,
          dimmed: false,
          highlighted: false,
        },
        style: { stroke: `${meta.color}66`, strokeWidth: 0.75 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 10, color: `${meta.color}88` },
        animated: false,
      };
    });

    setNodes(rfNodes);
    setEdges(rfEdges);

    // Apply dagre layout once after data loads
    if (!hasLayout.current) {
      hasLayout.current = true;
      applyDagreLayout(rfNodes, rfEdges, level).then((laid) => {
        setNodes(laid);
        setTimeout(() => fitView({ padding: 0.15, duration: 600 }), 50);
      });
    }
  }, [graphData, fitView, showDeadCode]);

  // ── Selection: highlight neighborhood, dim others ─────────

  const handleNodeSelect = useCallback(
    (nodeId: string | null) => {
      setSelectedNodeId(nodeId);

      if (!nodeId) {
        setHighlightedNodeIds(new Set());
        setHighlightedEdgeIds(new Set());
        setNodes((ns) =>
          ns.map((n) => ({ ...n, data: { ...n.data, dimmed: false, selected: false } })),
        );
        setEdges((es) =>
          es.map((e) => ({ ...e, data: { ...e.data, dimmed: false, highlighted: false } })),
        );
        return;
      }

      // Find directly connected nodes and edges
      const connectedNodeIds = new Set<string>([nodeId]);
      const connectedEdgeIds = new Set<string>();

      setEdges((currentEdges) => {
        currentEdges.forEach((e) => {
          if (e.source === nodeId || e.target === nodeId) {
            connectedEdgeIds.add(e.id);
            connectedNodeIds.add(e.source);
            connectedNodeIds.add(e.target);
          }
        });

        setHighlightedNodeIds(connectedNodeIds);
        setHighlightedEdgeIds(connectedEdgeIds);

        setNodes((ns) =>
          ns.map((n) => ({
            ...n,
            data: {
              ...n.data,
              dimmed: !connectedNodeIds.has(n.id),
              selected: n.id === nodeId,
            },
          })),
        );

        return currentEdges.map((e) => ({
          ...e,
          data: {
            ...e.data,
            dimmed: !connectedEdgeIds.has(e.id),
            highlighted: connectedEdgeIds.has(e.id),
          },
        }));
      });
    },
    [],
  );

  // ── React Flow event handlers ─────────────────────────────

  const onNodesChange = useCallback(
    (changes: NodeChange[]) =>
      setNodes((ns) => applyNodeChanges(changes, ns)),
    [],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) =>
      setEdges((es) => applyEdgeChanges(changes, es)),
    [],
  );

  const onSelectionChange = useCallback(
    ({ nodes: selNodes }: OnSelectionChangeParams) => {
      if (selNodes.length === 1) {
        handleNodeSelect(selNodes[0].id);
      } else if (selNodes.length === 0) {
        handleNodeSelect(null);
      }
    },
    [handleNodeSelect],
  );

  // ── Navigate to a node from search or panel ───────────────

  const navigateToNode = useCallback(
    (nodeId: string) => {
      handleNodeSelect(nodeId);
      setNodes((ns) => {
        const target = ns.find((n) => n.id === nodeId);
        if (target) {
          fitView({
            nodes: [target],
            padding: 0.5,
            duration: 500,
          });
        }
        return ns;
      });
    },
    [handleNodeSelect, fitView],
  );

  // ── Stats bar ─────────────────────────────────────────────

  const statsText = graphData
    ? `${graphData.nodes.length} nodes · ${graphData.edges.length} edges · ${graphData.total_files} files · ${graphData.total_symbols} symbols`
    : "";

  const limitations = graphData?.coverage?.limitations ?? [];

  // ── Render ────────────────────────────────────────────────

  return (
    <div
      className={cn("relative flex flex-col rounded-lg overflow-hidden border", className)}
      style={{ backgroundColor: "#07090c", borderColor: "#1a1f28" }}
    >
      {/* Top toolbar */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b shrink-0 flex-wrap gap-y-2"
        style={{ borderColor: "#1a1f28", backgroundColor: "#090c10" }}
      >
        {/* Level switcher */}
        <div className="flex items-center gap-1 rounded-md border p-0.5" style={{ borderColor: "#1a1f28" }}>
          {LEVELS.map((l) => (
            <button
              key={l.id}
              onClick={() => setLevel(l.id)}
              title={l.description}
              disabled={loading}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-all",
                level === l.id
                  ? "bg-teal-500/15 text-teal-400"
                  : "text-slate-500 hover:text-slate-300",
              )}
            >
              {l.icon}
              {l.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <GraphSearch repoId={repoId} onSelect={navigateToNode} />

        {/* Spacer */}
        <div className="flex-1" />

        {/* Dead code toggle + security badge */}
        <div className="flex items-center gap-2">
          {graphData && (() => {
            const deadCount = graphData.nodes.filter((n) => n.is_possibly_dead).length;
            if (deadCount > 0) {
              return (
                <button
                  onClick={() => setShowDeadCode((v) => !v)}
                  className={cn(
                    "flex items-center gap-1 text-[11px] rounded px-2 py-0.5 border transition-all",
                    showDeadCode
                      ? "text-slate-400 bg-slate-500/10 border-slate-500/30"
                      : "text-slate-600 bg-transparent border-slate-700/50",
                  )}
                  title={showDeadCode ? "Click to hide possibly dead code" : "Click to show possibly dead code"}
                >
                  <span className="w-2 h-2 rounded border border-dashed border-slate-500" />
                  {deadCount} dead {showDeadCode ? "visible" : "hidden"}
                </button>
              );
            }
            return null;
          })()}

          {graphData && graphData.nodes.filter((n) => n.is_security_sensitive).length > 0 && (
            <span className="flex items-center gap-1 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-0.5">
              <ShieldAlert className="h-3 w-3" />
              {graphData.nodes.filter((n) => n.is_security_sensitive).length} security-sensitive
            </span>
          )}
        </div>

        {/* Refresh */}
        <button
          onClick={() => fetchGraph(level)}
          disabled={loading}
          className="text-slate-500 hover:text-slate-300 transition-colors"
          title="Refresh graph"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </button>

        {/* Fit view */}
        <button
          onClick={() => fitView({ padding: 0.15, duration: 500 })}
          className="text-slate-500 hover:text-slate-300 transition-colors"
          title="Fit graph to view"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Stats bar */}
      {statsText && (
        <div
          className="flex items-center gap-3 px-4 py-1.5 border-b text-[11px] text-slate-600"
          style={{ borderColor: "#111418" }}
        >
          <span>{statsText}</span>
          {limitations.length > 0 && (
            <span className="flex items-center gap-1 text-amber-600">
              <AlertTriangle className="h-3 w-3" />
              {limitations.length} limitation(s) — hover for details
            </span>
          )}
        </div>
      )}

      {/* Main canvas area */}
      <div className="relative flex-1 min-h-0">
        {/* Loading overlay */}
        {loading && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/60">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="h-6 w-6 animate-spin text-teal-500" />
              <span className="text-xs text-slate-400">Building architecture graph…</span>
            </div>
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="absolute inset-0 z-30 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 max-w-sm text-center p-6">
              <AlertTriangle className="h-6 w-6 text-amber-400" />
              <p className="text-sm text-slate-300">{error}</p>
              <button
                onClick={() => fetchGraph(level)}
                className="text-xs text-teal-400 hover:text-teal-300"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && nodes.length === 0 && (
          <div className="absolute inset-0 z-10 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-center p-6">
              <Info className="h-6 w-6 text-slate-600" />
              <p className="text-sm text-slate-400">No graph data available at this level.</p>
              <p className="text-xs text-slate-600">
                Try a different level or wait for indexing to complete.
              </p>
            </div>
          </div>
        )}

        {/* React Flow canvas */}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onSelectionChange={onSelectionChange}
          onPaneClick={() => handleNodeSelect(null)}
          fitView={false}
          minZoom={0.08}
          maxZoom={2.5}
          defaultEdgeOptions={{ type: "custom", animated: false }}
          proOptions={{ hideAttribution: true }}
          style={{ background: "transparent" }}
        >
          {/* Dark dot grid background */}
          <Background
            variant={BackgroundVariant.Dots}
            gap={24}
            size={1}
            color="#1a1f28"
          />

          {/* Controls */}
          <Controls
            showInteractive={false}
            style={{
              backgroundColor: "#0c0f14",
              borderColor: "#1a1f28",
              boxShadow: "none",
            }}
          />

          {/* Mini-map */}
          <MiniMap
            nodeColor={(n) => {
              const type = (n.data as GraphNodeData)?.type ?? "file";
              return NODE_TYPE_META[type]?.color ?? "#5eead4";
            }}
            maskColor="rgba(7,9,12,0.85)"
            style={{
              backgroundColor: "#09090d",
              borderColor: "#1a1f28",
              border: "1px solid",
              borderRadius: 6,
            }}
          />
        </ReactFlow>

        {/* Floating bottom-left: legend + coverage */}
        <div className="absolute bottom-10 left-3 z-10 flex flex-col gap-2 w-52">
          <GraphLegend />
          {/* Coverage limitations */}
          {limitations.length > 0 && (
            <div
              className="rounded-md border p-2.5 text-[10px] text-slate-500 space-y-1"
              style={{ backgroundColor: "#09090d", borderColor: "#1a1f28" }}
            >
              <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
                Limitations
              </p>
              {limitations.map((l, i) => (
                <p key={i} className="leading-snug">{l}</p>
              ))}
            </div>
          )}
        </div>

        {/* Node details panel — slides in from right */}
        {selectedNodeId && (
          <NodeDetailsPanel
            repoId={repoId}
            nodeId={selectedNodeId}
            onClose={() => handleNodeSelect(null)}
            onNavigate={navigateToNode}
          />
        )}
      </div>
    </div>
  );
}
