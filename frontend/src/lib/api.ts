/**
 * PRISM API client — typed wrappers for all backend endpoints.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }

  return res.json();
}

// ── Types ──────────────────────────────────────────────────

export interface Repository {
  id: string;
  url: string;
  provider: string;
  full_name: string;
  default_branch: string;
  mirror_path: string | null;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LanguageStat {
  language: string;
  file_count: number;
  symbol_count: number;
  percentage: number;
}

export interface FileChangeFrequency {
  file_path: string;
  change_count: number;
  last_modified: string | null;
  reference_count: number;
  status: string;
}

export interface IndexVersion {
  id: string;
  repository_id: string;
  commit_sha: string;
  status: string;
  languages: Record<string, number>;
  files_indexed: number;
  symbols_indexed: number;
  relationships_indexed: number;
  files_unsupported: string[];
  errors: string[];
  warnings: string[];
  started_at: string | null;
  completed_at: string | null;
}

export interface RepositoryOverview {
  repository: Repository;
  commit_sha: string | null;
  default_branch: string;
  languages: LanguageStat[];
  total_files: number;
  total_symbols: number;
  total_relationships: number;
  frequently_changed: FileChangeFrequency[];
  recent_commits: Array<{
    sha: string;
    message: string;
    author: string;
    committed_at: string | null;
  }>;
  index_status: string;
  index_version: IndexVersion | null;
}

export interface IngestionStatus {
  repository_id: string;
  job_id: string;
  job_type: string;
  status: string;
  progress: number;
  commit_sha: string | null;
  current_step: string | null;
  languages_detected: Record<string, number>;
  files_indexed: number;
  symbols_indexed: number;
  errors: string[];
  warnings: string[];
  error_message: string | null;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  file_path: string | null;
  language: string | null;
  change_count: number;
  last_modified: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation_type: string;
  certainty: string;
}

export interface CodeGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Finding {
  id: string;
  title: string;
  description: string;
  severity: string;
  confidence: string;
  file_path: string | null;
  line_range: number[];
  category: string | null;
  rule_id: string | null;
  scanner_source: string;
  is_blocking: boolean;
  evidence?: Array<{
    file_path: string;
    line_range: number[];
    source: string;
  }>;
}

export interface CheckResult {
  name: string;
  status: string;
  source: string;
  details: string | null;
}

export interface ReviewReport {
  id: string;
  pull_request_id: string;
  repository_id: string;
  commit_sha: string;
  base_sha: string;
  review_state: string;
  change_summary: string;
  functional_purpose: string | null;
  affected_components: Array<{
    file_path: string;
    status: string;
    language: string | null;
    symbols_changed: number;
  }>;
  potential_security_impacts: Array<{
    description: string;
    severity: string;
    confidence: string;
    evidence_ref: string[];
  }>;
  executive_summary: Record<string, unknown>;
  technical_evidence: Record<string, unknown>;
  findings: Finding[];
  uncertainty: string | null;
  analysis_coverage: Record<string, unknown>;
  recommended_action: string | null;
  required_checks: CheckResult[];
  llm_model: string | null;
  is_stale: boolean;
  created_at: string;
}

export interface PullRequest {
  id: string;
  pr_number: number;
  title: string;
  author: string | null;
  base_sha: string | null;
  head_sha: string | null;
  base_branch: string;
  head_branch: string;
  body: string | null;
  created_at: string;
  // enhanced fields
  state: string; // open | closed | merged
  merged_at: string | null;
  merge_commit_sha: string | null;
  additions: number;
  deletions: number;
  changed_files: number;
  review_state: string | null;       // PRISM analysis state
  github_review_state: string | null; // APPROVED | CHANGES_REQUESTED | PENDING
  github_configured: boolean;
}

export interface CommitItem {
  id: string;
  sha: string;
  short_sha: string;
  message: string;
  message_headline: string;
  author_name: string;
  author_email: string | null;
  committed_at: string | null;
  stats_additions: number;
  stats_deletions: number;
  files_changed: string[];
  files_changed_count: number;
  parent_shas: string[];
  is_merge: boolean;
  linked_pr: {
    id: string;
    pr_number: number;
    title: string;
    state: string;
    review_state: string | null;
  } | null;
  extracted_pr_number: number | null;
}

// Commit is the basic type; CommitItem is the enriched version from /commits
export interface Commit {
  id: string;
  sha: string;
  message: string;
  author_name: string;
  committed_at: string | null;
  stats_additions: number;
  stats_deletions: number;
  files_changed: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  llm_provider: string;
  llm_model: string;
  llm_available: boolean;
}

export interface SettingsResponse {
  llm: {
    provider: string;
    model: string;
    base_url: string;
    is_available: boolean;
    model_info: Record<string, unknown>;
  };
  integrations: Array<{
    name: string;
    type: string;
    configured: boolean;
    status: string;
    details: Record<string, unknown>;
  }>;
  database_type: string;
}

// ── API Methods ────────────────────────────────────────────

export const api = {
  // Health
  health: () => apiFetch<HealthResponse>("/health"),

  // Repositories
  listRepos: () =>
    apiFetch<{ repositories: Repository[]; total: number }>("/api/repositories"),

  getRepo: (id: string) => apiFetch<Repository>(`/api/repositories/${id}`),

  connectRepo: (url: string, provider?: string, branch?: string) =>
    apiFetch<Repository>("/api/repositories", {
      method: "POST",
      body: JSON.stringify({ url, provider, branch }),
    }),

  getOverview: (id: string) =>
    apiFetch<RepositoryOverview>(`/api/repositories/${id}/overview`),

  syncRepo: (id: string) =>
    apiFetch<{ triggered: boolean; repository_id: string; head_sha: string | null; last_synced_at: string | null }>(
      `/api/repositories/${id}/sync`,
      { method: "POST" }
    ),

  getIngestionStatus: (id: string) =>
    apiFetch<IngestionStatus>(`/api/repositories/${id}/ingestion-status`),

  getCodeGraph: (id: string, limit?: number) =>
    apiFetch<CodeGraph>(`/api/repositories/${id}/graph${limit ? `?limit=${limit}` : ""}`),

  getCommits: (id: string, limit = 50) =>
    apiFetch<{ commits: CommitItem[]; total: number }>(
      `/api/repositories/${id}/commits?limit=${limit}`
    ),

  // Reviews
  startReview: (repoId: string, data: {
    base_sha: string;
    head_sha: string;
    pr_number?: number;
    pr_title?: string;
    pr_author?: string;
    pr_body?: string;
  }) =>
    apiFetch<{ job_id: string; pr_id: string | null; status: string; message: string }>(
      `/api/repositories/${repoId}/reviews`,
      { method: "POST", body: JSON.stringify(data) }
    ),

  getReviewReport: (repoId: string, prId: string) =>
    apiFetch<ReviewReport>(`/api/repositories/${repoId}/reviews/${prId}`),

  getPullRequests: (repoId: string) =>
    apiFetch<{ pull_requests: PullRequest[]; total: number; github_configured: boolean }>(
      `/api/repositories/${repoId}/pull-requests`
    ),

  approvePR: (repoId: string, prId: string) =>
    apiFetch<{ success: boolean; message: string; html_url: string | null; pr_number: number }>(
      `/api/repositories/${repoId}/pull-requests/${prId}/approve`,
      { method: "POST" }
    ),

  mergePR: (repoId: string, prId: string, mergeMethod = "squash") =>
    apiFetch<{ success: boolean; message: string; merge_commit_sha: string | null; pr_number: number }>(
      `/api/repositories/${repoId}/pull-requests/${prId}/merge?merge_method=${mergeMethod}`,
      { method: "POST" }
    ),

  explainCommit: (repoId: string, commitSha: string) =>
    apiFetch<{ sha: string; explanation: string; cached: boolean; model: string | null }>(
      `/api/repositories/${repoId}/commits/${commitSha}/explain`
    ),

  // Settings
  getSettings: () => apiFetch<SettingsResponse>("/api/settings"),

  // MCP
  listMcpTools: () =>
    apiFetch<{ tools: Array<{ name: string; description: string }> }>("/api/mcp/tools"),

  // Architecture Graph
  getArchitectureGraph: (repoId: string, level: "module" | "file" | "symbol" = "module", limit = 200) =>
    apiFetch<import("./graphTypes").ArchGraphData>(
      `/api/repositories/${repoId}/architecture-graph?level=${level}&limit=${limit}`
    ),

  getNodeDetails: (repoId: string, nodeId: string) =>
    apiFetch<import("./graphTypes").NodeDetails>(
      `/api/repositories/${repoId}/architecture-graph/node?node_id=${encodeURIComponent(nodeId)}`
    ),

  searchGraph: (repoId: string, query: string, limit = 20) =>
    apiFetch<import("./graphTypes").SearchResponse>(
      `/api/repositories/${repoId}/architecture-graph/search?q=${encodeURIComponent(query)}&limit=${limit}`
    ),

  tracePath: (repoId: string, source: string, target: string, maxDepth = 5) =>
    apiFetch<import("./graphTypes").PathTraceResponse>(
      `/api/repositories/${repoId}/architecture-graph/path?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}&max_depth=${maxDepth}`
    ),
};
