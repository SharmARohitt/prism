/**
 * Graph data contract for the PRISM architecture graph.
 *
 * Every node explains what a component is, its type, its module grouping,
 * and relationship counts. Every edge explains the relationship type,
 * direction, and evidence confidence.
 */

// ── Node types ─────────────────────────────────────────────

export type GraphNodeType =
  | "repository"
  | "module"
  | "file"
  | "class"
  | "function"
  | "method"
  | "interface"
  | "variable"
  | "endpoint"
  | "import"
  | "test"
  | "config"
  | "security_control"
  | "security_finding";

export type EvidenceClass =
  | "statically_verified"
  | "inferred"
  | "runtime_observed"
  | "unknown";

export type RelationType =
  | "imports"
  | "calls"
  | "references"
  | "contains"
  | "implements"
  | "inherits"
  | "depends_on"
  | "invokes_api"
  | "reads_config"
  | "writes_data"
  | "tested_by"
  | "protected_by"
  | "potentially_affected_by";

export type GraphLevel = "module" | "file" | "symbol";

// ── Graph node ─────────────────────────────────────────────

export interface ArchGraphNode {
  id: string;
  label: string;
  type: GraphNodeType;
  file_path: string | null;
  language: string | null;
  module: string | null;
  symbol_count: number;
  incoming_count: number;
  outgoing_count: number;
  change_count: number;
  last_modified: string | null;
  is_security_sensitive: boolean;
  evidence_class: EvidenceClass;
  qualified_name: string | null;
  start_line: number | null;
  end_line: number | null;
  signature: string | null;
  is_possibly_dead: boolean;
}

// ── Graph edge ─────────────────────────────────────────────

export interface ArchGraphEdge {
  id: string;
  source: string;
  target: string;
  relation_type: RelationType;
  evidence_class: EvidenceClass;
  line_number: number | null;
  source_file: string | null;
  target_file: string | null;
  source_symbol: string | null;
  target_symbol: string | null;
}

// ── Full graph response ────────────────────────────────────

export interface ArchGraphData {
  nodes: ArchGraphNode[];
  edges: ArchGraphEdge[];
  level: GraphLevel;
  total_symbols: number;
  total_files: number;
  coverage: {
    languages_analyzed: string[];
    relationship_types: string[];
    unsupported_files: number;
    limitations: string[];
  };
}

// ── Node details ───────────────────────────────────────────

export interface NodeRelationship {
  node_id: string;
  label: string;
  type: GraphNodeType;
  file_path: string | null;
  relation_type: RelationType;
  evidence_class: EvidenceClass;
  direction: "incoming" | "outgoing";
  line_number: number | null;
}

export interface NodeDetails {
  node_id: string;
  label: string;
  type: GraphNodeType;
  file_path: string | null;
  language: string | null;
  module: string | null;
  qualified_name: string | null;
  signature: string | null;
  start_line: number | null;
  end_line: number | null;
  incoming: NodeRelationship[];
  outgoing: NodeRelationship[];
  incoming_count: number;
  outgoing_count: number;
  change_count: number;
  last_modified: string | null;
  is_security_sensitive: boolean;
  plain_english: string;
  what_uses_it: string[];
  what_it_uses: string[];
  evidence: string[];
  impact: string;
}

// ── Search ─────────────────────────────────────────────────

export interface SearchResult {
  node_id: string;
  label: string;
  type: GraphNodeType;
  file_path: string | null;
  module: string | null;
  language: string | null;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

// ── Path tracing ───────────────────────────────────────────

export interface PathStep {
  node_id: string;
  label: string;
  type: GraphNodeType;
  file_path: string | null;
  relation_type: RelationType | null;
  evidence_class: EvidenceClass | null;
  plain_english: string;
}

export interface PathTraceResponse {
  found: boolean;
  steps: PathStep[];
  message: string | null;
}

// ── Visual constants ───────────────────────────────────────

export const NODE_TYPE_META: Record<
  GraphNodeType,
  { color: string; shape: string; icon: string; label: string }
> = {
  repository: { color: "#5eead4", shape: "diamond", icon: "▣", label: "Repository" },
  module: { color: "#34d399", shape: "hexagon", icon: "📁", label: "Module" },
  file: { color: "#60a5fa", shape: "rect", icon: "📄", label: "File" },
  class: { color: "#c084fc", shape: "rect", icon: "C", label: "Class" },
  function: { color: "#5eead4", shape: "rect", icon: "ƒ", label: "Function" },
  method: { color: "#67e8f9", shape: "rect", icon: "m", label: "Method" },
  interface: { color: "#fbbf24", shape: "rect", icon: "I", label: "Interface" },
  variable: { color: "#94a3b8", shape: "circle", icon: "v", label: "Variable" },
  endpoint: { color: "#f87171", shape: "rect", icon: "→", label: "API Endpoint" },
  import: { color: "#94a3b8", shape: "circle", icon: "↑", label: "Import" },
  test: { color: "#84cc16", shape: "rect", icon: "✓", label: "Test" },
  config: { color: "#a78bfa", shape: "rect", icon: "⚙", label: "Configuration" },
  security_control: { color: "#22d3ee", shape: "shield", icon: "🛡", label: "Security Control" },
  security_finding: { color: "#fb7185", shape: "triangle", icon: "!", label: "Security Finding" },
};

export const EDGE_TYPE_META: Record<
  RelationType,
  { label: string; color: string; dashed: boolean }
> = {
  imports: { label: "imports", color: "#60a5fa", dashed: false },
  calls: { label: "calls", color: "#5eead4", dashed: false },
  references: { label: "references", color: "#94a3b8", dashed: false },
  contains: { label: "contains", color: "#475569", dashed: false },
  implements: { label: "implements", color: "#c084fc", dashed: false },
  inherits: { label: "inherits", color: "#c084fc", dashed: false },
  depends_on: { label: "depends on", color: "#fbbf24", dashed: false },
  invokes_api: { label: "invokes API", color: "#f87171", dashed: false },
  reads_config: { label: "reads config", color: "#a78bfa", dashed: false },
  writes_data: { label: "writes data", color: "#fb923c", dashed: false },
  tested_by: { label: "tested by", color: "#84cc16", dashed: false },
  protected_by: { label: "protected by", color: "#22d3ee", dashed: false },
  potentially_affected_by: { label: "affected by", color: "#fb7185", dashed: true },
};

export const EVIDENCE_META: Record<EvidenceClass, { label: string; color: string }> = {
  statically_verified: { label: "Statically Verified", color: "#34d399" },
  inferred: { label: "Inferred", color: "#fbbf24" },
  runtime_observed: { label: "Runtime Observed", color: "#60a5fa" },
  unknown: { label: "Unknown", color: "#64748b" },
};
