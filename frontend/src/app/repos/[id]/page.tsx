"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  GitBranch,
  FileCode,
  Boxes,
  Clock,
  TrendingUp,
  GitCommit,
  AlertTriangle,
  RefreshCw,
  CheckCircle2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type RepositoryOverview } from "@/lib/api";
import { ArchitectureGraph } from "@/components/graph/ArchitectureGraph";
import { shortSha, formatDate } from "@/lib/utils";

export default function RepositoryDashboard() {
  const params = useParams();
  const router = useRouter();
  const repoId = params.id as string;
  const [overview, setOverview] = useState<RepositoryOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const fetchOverview = useCallback(async () => {
    try {
      const ov = await api.getOverview(repoId);
      setOverview(ov);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load repository");
    } finally {
      setLoading(false);
    }
  }, [repoId]);

  // Auto-refresh the overview every 60 seconds so new commits appear
  useEffect(() => {
    fetchOverview();
    const interval = setInterval(fetchOverview, 60_000);
    return () => clearInterval(interval);
  }, [fetchOverview]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const result = await api.syncRepo(repoId);
      setSyncMsg(
        result.head_sha
          ? `Up to date at ${result.head_sha.substring(0, 12)}`
          : "Sync triggered",
      );
      // Refresh overview after sync
      await fetchOverview();
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8">
        <div className="text-sm text-prism-text-muted animate-pulse">
          Loading repository intelligence…
        </div>
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8">
        <div className="text-sm text-prism-danger">{error || "Repository not found"}</div>
        <Button variant="outline" className="mt-4" onClick={() => router.push("/")}>
          Back to Repositories
        </Button>
      </div>
    );
  }

  const repo = overview.repository;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">{repo.full_name}</h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-prism-text-muted">
            <span className="flex items-center gap-1">
              <GitBranch className="h-3.5 w-3.5" />
              {overview.default_branch}
            </span>
            <span className="font-mono text-xs">{shortSha(overview.commit_sha)}</span>
            <Badge variant={overview.index_status === "completed" ? "success" : "warning"}>
              {overview.index_status}
            </Badge>
          </div>
        </div>
        <div className="flex gap-2 items-center">
          {syncMsg && (
            <span className="text-xs text-prism-text-muted flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3 text-prism-success" />
              {syncMsg}
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleSync}
            disabled={syncing}
            title="Check for new commits now"
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => router.push(`/repos/${repoId}/timeline`)}
          >
            <Clock className="mr-1.5 h-3.5 w-3.5" />
            Timeline
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => router.push(`/repos/${repoId}/settings`)}
          >
            Settings
          </Button>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard
          icon={<FileCode className="h-4 w-4" />}
          label="Files"
          value={overview.total_files}
        />
        <StatCard
          icon={<Boxes className="h-4 w-4" />}
          label="Symbols"
          value={overview.total_symbols}
        />
        <StatCard
          icon={<GitBranch className="h-4 w-4" />}
          label="Relationships"
          value={overview.total_relationships}
        />
        <StatCard
          icon={<GitCommit className="h-4 w-4" />}
          label="Commits"
          value={overview.recent_commits.length}
        />
      </div>

      {/* Language distribution */}
      {overview.languages.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Language Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {overview.languages.map((lang) => (
                <div key={lang.language} className="flex items-center gap-3">
                  <span className="w-24 text-sm font-medium">{lang.language}</span>
                  <div className="flex-1 h-2 rounded-full bg-secondary overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${lang.percentage}%`,
                        backgroundColor: "#2dd4bf",
                        opacity: 0.7,
                      }}
                    />
                  </div>
                  <span className="w-28 text-xs text-prism-text-muted text-right">
                    {lang.file_count} files · {lang.symbol_count} sym
                  </span>
                  <span className="w-10 text-xs text-prism-text-muted text-right">
                    {lang.percentage}%
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Architecture Graph ────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-base font-semibold">Code Architecture Graph</h2>
            <p className="text-xs text-prism-text-muted mt-0.5">
              Click any node to explore its relationships and evidence. Switch levels to
              change the level of detail.
            </p>
          </div>
        </div>

        {overview.index_status === "completed" ? (
          <ArchitectureGraph repoId={repoId} className="h-[600px] w-full" />
        ) : (
          <div
            className="flex items-center justify-center h-48 rounded-lg border text-sm text-prism-text-muted"
            style={{ borderColor: "#1a1f28", backgroundColor: "#0c0f14" }}
          >
            Indexing in progress — graph will appear when indexing completes.
          </div>
        )}
      </div>

      {/* Frequently changed files */}
      {overview.frequently_changed.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4" />
              Frequently Changed Files
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {overview.frequently_changed.map((file, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-md border border-border bg-card/50 px-3 py-2"
                >
                  <span className="font-mono text-xs truncate max-w-[55%]">
                    {file.file_path}
                  </span>
                  <div className="flex items-center gap-3 text-xs text-prism-text-muted">
                    <span>{file.change_count} changes</span>
                    <span>{formatDate(file.last_modified)}</span>
                    <Badge
                      variant={
                        file.status === "possibly_unused"
                          ? "warning"
                          : file.status === "active"
                          ? "success"
                          : "secondary"
                      }
                      className="text-xs"
                    >
                      {file.status.replace(/_/g, " ")}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent commits */}
      {overview.recent_commits.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Recent Commits</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {overview.recent_commits.map((commit, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 rounded-md border border-border bg-card/50 px-3 py-2"
                >
                  <GitCommit className="h-4 w-4 text-prism-text-muted mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{commit.message}</p>
                    <p className="text-xs text-prism-text-muted mt-0.5">
                      {commit.author} · {formatDate(commit.committed_at)}
                    </p>
                  </div>
                  <span className="font-mono text-xs text-prism-text-muted shrink-0">
                    {commit.sha}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Index status details */}
      {overview.index_version && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Index Status Details
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <MiniStat label="Files indexed" value={overview.index_version.files_indexed} />
              <MiniStat label="Symbols extracted" value={overview.index_version.symbols_indexed} />
              <MiniStat
                label="Relationships"
                value={overview.index_version.relationships_indexed}
              />
            </div>
            {overview.index_version.files_unsupported.length > 0 && (
              <div className="pt-2 border-t border-border">
                <p className="text-xs text-prism-text-muted mb-1">
                  Unsupported files ({overview.index_version.files_unsupported.length}):
                </p>
                <div className="flex flex-wrap gap-1">
                  {overview.index_version.files_unsupported.slice(0, 8).map((f, i) => (
                    <Badge key={i} variant="outline" className="text-xs font-mono">
                      {f.split("/").pop()}
                    </Badge>
                  ))}
                  {overview.index_version.files_unsupported.length > 8 && (
                    <span className="text-xs text-prism-text-muted">
                      +{overview.index_version.files_unsupported.length - 8} more
                    </span>
                  )}
                </div>
              </div>
            )}
            {overview.index_version.errors.length > 0 && (
              <div className="pt-2 border-t border-border">
                <p className="text-xs text-prism-danger mb-1">
                  Errors ({overview.index_version.errors.length}):
                </p>
                {overview.index_version.errors.slice(0, 3).map((e, i) => (
                  <p key={i} className="text-xs text-prism-text-muted font-mono">
                    {e}
                  </p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-md border border-border bg-card/50 px-4 py-3">
      <div className="flex items-center gap-2 text-prism-text-muted">
        {icon}
        <span className="text-xs">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums">
        {value.toLocaleString()}
      </p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border bg-card/50 px-3 py-2">
      <p className="text-xs text-prism-text-muted">{label}</p>
      <p className="text-lg font-semibold mt-0.5 tabular-nums">
        {value.toLocaleString()}
      </p>
    </div>
  );
}
