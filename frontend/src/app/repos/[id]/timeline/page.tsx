"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import {
  GitCommit,
  GitPullRequest,
  GitMerge,
  Calendar,
  Plus,
  Minus,
  FileText,
  ShieldCheck,
  Check,
  X,
  Loader2,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Link2,
  AlertCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type PullRequest, type CommitItem } from "@/lib/api";
import { formatDate, formatDateTime, reviewStateColor, reviewStateLabel, cn } from "@/lib/utils";

// ── Timeline item ───────────────────────────────────────────

type TimelineEntry =
  | { kind: "commit"; commit: CommitItem; timestamp: string | null }
  | { kind: "pr"; pr: PullRequest; timestamp: string | null };

export default function TimelinePage() {
  const params = useParams();
  const repoId = params.id as string;
  const [commits, setCommits] = useState<CommitItem[]>([]);
  const [prs, setPrs] = useState<PullRequest[]>([]);
  const [githubConfigured, setGithubConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [expandedCommit, setExpandedCommit] = useState<string | null>(null);
  const [explanations, setExplanations] = useState<Record<string, { text: string; loading: boolean; model: string | null }>>({});

  const loadData = useCallback(async () => {
    try {
      const [c, p] = await Promise.all([
        api.getCommits(repoId, 50),
        api.getPullRequests(repoId),
      ]);
      setCommits(c.commits);
      setPrs(p.pull_requests);
      setGithubConfigured(p.github_configured);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [repoId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Fetch explanation for a commit when it's expanded
  const fetchExplanation = useCallback(
    async (sha: string) => {
      if (explanations[sha]?.text || explanations[sha]?.loading) return;
      setExplanations((prev) => ({ ...prev, [sha]: { text: "", loading: true, model: null } }));
      try {
        const result = await api.explainCommit(repoId, sha);
        setExplanations((prev) => ({
          ...prev,
          [sha]: { text: result.explanation, loading: false, model: result.model },
        }));
      } catch (e) {
        setExplanations((prev) => ({
          ...prev,
          [sha]: {
            text: "Could not generate explanation. Check that the LLM is running.",
            loading: false,
            model: null,
          },
        }));
      }
    },
    [repoId, explanations],
  );

  const toggleCommit = (sha: string) => {
    if (expandedCommit === sha) {
      setExpandedCommit(null);
    } else {
      setExpandedCommit(sha);
      fetchExplanation(sha);
    }
  };

  // ── Merge commits and PRs into one timeline ───────────────

  const timeline: TimelineEntry[] = [
    ...commits.map((c) => ({ kind: "commit" as const, commit: c, timestamp: c.committed_at })),
    ...prs
      .filter((p) => p.merged_at)
      .map((p) => ({ kind: "pr" as const, pr: p, timestamp: p.merged_at })),
  ].sort((a, b) => {
    const ta = a.timestamp ? new Date(a.timestamp).getTime() : 0;
    const tb = b.timestamp ? new Date(b.timestamp).getTime() : 0;
    return tb - ta; // newest first
  });

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="flex items-center gap-2 text-sm text-prism-text-muted animate-pulse">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading timeline…
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">Change Timeline</h1>
          <p className="text-sm text-prism-text-muted mt-1">
            Every commit and PR merge — explained in plain English
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-xs">
            {commits.length} commits
          </Badge>
          <Badge variant="secondary" className="text-xs">
            {prs.length} PRs
          </Badge>
          {githubConfigured && (
            <Badge variant="success" className="text-xs gap-1">
              <ShieldCheck className="h-3 w-3" />
              GitHub linked
            </Badge>
          )}
        </div>
      </div>

      {/* Unified timeline */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCommit className="h-4 w-4" />
            Activity Feed ({timeline.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {timeline.length === 0 ? (
            <p className="text-sm text-prism-text-muted py-4">
              No activity yet. Re-ingest the repository to load commit history.
            </p>
          ) : (
            <div className="relative space-y-3 pl-6 before:absolute before:left-[7px] before:top-2 before:bottom-2 before:w-px before:bg-border">
              {timeline.map((entry, i) => {
                if (entry.kind === "pr") {
                  return <PRTimelineCard key={`pr-${entry.pr.id}`} pr={entry.pr} repoId={repoId} githubConfigured={githubConfigured} onApprove={loadData} />;
                }
                return (
                  <CommitTimelineCard
                    key={`c-${entry.commit.sha}`}
                    commit={entry.commit}
                    isExpanded={expandedCommit === entry.commit.sha}
                    onToggle={() => toggleCommit(entry.commit.sha)}
                    explanation={explanations[entry.commit.sha]}
                  />
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Commit card ─────────────────────────────────────────────

function CommitTimelineCard({
  commit,
  isExpanded,
  onToggle,
  explanation,
}: {
  commit: CommitItem;
  isExpanded: boolean;
  onToggle: () => void;
  explanation?: { text: string; loading: boolean; model: string | null };
}) {
  const isMerge = commit.is_merge;
  const hasPR = commit.linked_pr || commit.extracted_pr_number;

  return (
    <div className="relative">
      {/* Timeline dot */}
      <div
        className={cn(
          "absolute -left-[18px] top-1.5 h-3 w-3 rounded-full border-2",
          isMerge
            ? "border-purple-400 bg-prism-bg"
            : hasPR
            ? "border-blue-400 bg-prism-bg"
            : "border-prism-mint bg-prism-bg",
        )}
      />

      <div
        className={cn(
          "rounded-md border bg-card/50 transition-all",
          isMerge ? "border-purple-500/30 bg-purple-500/5" : "border-border",
        )}
      >
        {/* Top row */}
        <div
          className="flex items-start justify-between gap-2 px-3 py-2 cursor-pointer select-none"
          onClick={onToggle}
        >
          <div className="flex items-start gap-2 min-w-0 flex-1">
            {isMerge ? (
              <GitMerge className="h-4 w-4 text-purple-400 mt-0.5 shrink-0" />
            ) : (
              <GitCommit className="h-4 w-4 text-prism-text-muted mt-0.5 shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              {/* Badges */}
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                {isMerge && (
                  <Badge variant="secondary" className="text-[10px] bg-purple-500/20 text-purple-300">
                    merge commit
                  </Badge>
                )}
                {commit.linked_pr && (
                  <Badge variant="secondary" className="text-[10px] bg-blue-500/20 text-blue-300 gap-0.5">
                    <Link2 className="h-2.5 w-2.5" />
                    PR #{commit.linked_pr.pr_number}
                  </Badge>
                )}
                {!commit.linked_pr && commit.extracted_pr_number && (
                  <Badge variant="outline" className="text-[10px] text-blue-400">
                    PR #{commit.extracted_pr_number}
                  </Badge>
                )}
                {commit.linked_pr?.review_state && (
                  <Badge
                    className="text-[10px]"
                    style={{
                      backgroundColor: `${reviewStateColor(commit.linked_pr.review_state)}20`,
                      color: reviewStateColor(commit.linked_pr.review_state),
                      border: `1px solid ${reviewStateColor(commit.linked_pr.review_state)}40`,
                    }}
                  >
                    {reviewStateLabel(commit.linked_pr.review_state)}
                  </Badge>
                )}
              </div>
              {/* Commit message headline */}
              <p className="text-sm font-medium truncate">
                {commit.message_headline || commit.message}
              </p>
              {/* Author + date */}
              <div className="flex items-center gap-2 mt-0.5 text-xs text-prism-text-muted">
                <span>{commit.author_name}</span>
                <span className="flex items-center gap-0.5">
                  <Calendar className="h-2.5 w-2.5" />
                  {formatDateTime(commit.committed_at)}
                </span>
                <span className="font-mono text-[10px]">{commit.short_sha}</span>
              </div>
            </div>
          </div>

          {/* Stats + expand button */}
          <div className="flex items-center gap-2 shrink-0">
            <div className="flex items-center gap-1 text-xs">
              <span className="text-prism-success flex items-center gap-0.5">
                <Plus className="h-2.5 w-2.5" />
                {commit.stats_additions}
              </span>
              <span className="text-prism-danger flex items-center gap-0.5">
                <Minus className="h-2.5 w-2.5" />
                {commit.stats_deletions}
              </span>
              <span className="text-prism-text-muted">
                {commit.files_changed_count} files
              </span>
            </div>
            {isExpanded ? (
              <ChevronUp className="h-3.5 w-3.5 text-prism-text-muted" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-prism-text-muted" />
            )}
          </div>
        </div>

        {/* Expanded content */}
        {isExpanded && (
          <div className="border-t border-border px-3 py-2.5 space-y-2.5 animate-fade-in">
            {/* Plain-English explanation */}
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <Sparkles className="h-3 w-3 text-prism-mint" />
                <span className="text-xs font-semibold text-prism-text-muted uppercase tracking-wide">
                  What changed
                </span>
                {explanation?.model && (
                  <span className="text-[10px] text-prism-text-muted ml-auto">
                    via {explanation.model}
                  </span>
                )}
              </div>
              {explanation?.loading ? (
                <div className="flex items-center gap-2 text-xs text-prism-text-muted">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Analyzing changes…
                </div>
              ) : (
                <p className="text-sm text-slate-200 leading-relaxed">
                  {explanation?.text || "Click to load explanation…"}
                </p>
              )}
            </div>

            {/* Changed files list */}
            {commit.files_changed && commit.files_changed.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 mb-1">
                  <FileText className="h-3 w-3 text-prism-text-muted" />
                  <span className="text-xs font-semibold text-prism-text-muted uppercase tracking-wide">
                    Files ({commit.files_changed.length})
                  </span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {commit.files_changed.slice(0, 15).map((f, i) => (
                    <span
                      key={i}
                      className="text-[10px] font-mono text-prism-text-muted bg-secondary/50 rounded px-1.5 py-0.5 truncate max-w-[200px]"
                      title={f}
                    >
                      {f}
                    </span>
                  ))}
                  {commit.files_changed.length > 15 && (
                    <span className="text-[10px] text-prism-text-muted">
                      +{commit.files_changed.length - 15} more
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Parent SHAs */}
            {commit.parent_shas && commit.parent_shas.length > 0 && (
              <div className="text-[10px] text-prism-text-muted font-mono">
                parents: {commit.parent_shas.map((p) => p.substring(0, 12)).join(", ")}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── PR timeline card ─────────────────────────────────────────

function PRTimelineCard({
  pr,
  repoId,
  githubConfigured,
  onApprove,
}: {
  pr: PullRequest;
  repoId: string;
  githubConfigured: boolean;
  onApprove: () => void;
}) {
  const [approving, setApproving] = useState(false);
  const [approveMsg, setApproveMsg] = useState<string | null>(null);
  const [approveSuccess, setApproveSuccess] = useState(false);

  const handleApprove = async () => {
    setApproving(true);
    setApproveMsg(null);
    try {
      const result = await api.approvePR(repoId, pr.id);
      setApproveSuccess(result.success);
      setApproveMsg(result.message);
      if (result.success) onApprove();
    } catch (e) {
      setApproveSuccess(false);
      setApproveMsg(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  };

  const stateColor =
    pr.state === "merged" ? "#a78bfa" : pr.state === "closed" ? "#94a3b8" : "#34d399";
  const canApprove =
    githubConfigured &&
    pr.state !== "merged" &&
    pr.review_state &&
    pr.review_state !== "blocked_by_finding" &&
    pr.review_state !== "analysis_incomplete" &&
    pr.github_review_state !== "APPROVED";

  return (
    <div className="relative">
      {/* Timeline dot — blue for PR merge */}
      <div className="absolute -left-[18px] top-1.5 h-3 w-3 rounded-full border-2 border-blue-400 bg-prism-bg" />

      <div className="rounded-md border border-blue-500/30 bg-blue-500/5 px-3 py-2">
        {/* Top row */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-start gap-2 min-w-0 flex-1">
            <GitPullRequest className="h-4 w-4 text-blue-400 mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                <Badge variant="secondary" className="text-[10px] bg-blue-500/20 text-blue-300">
                  PR #{pr.pr_number}
                </Badge>
                <Badge
                  className="text-[10px]"
                  style={{
                    backgroundColor: `${stateColor}20`,
                    color: stateColor,
                    border: `1px solid ${stateColor}40`,
                  }}
                >
                  {pr.state}
                </Badge>
                {pr.review_state && (
                  <Badge
                    className="text-[10px]"
                    style={{
                      backgroundColor: `${reviewStateColor(pr.review_state)}20`,
                      color: reviewStateColor(pr.review_state),
                      border: `1px solid ${reviewStateColor(pr.review_state)}40`,
                    }}
                  >
                    {reviewStateLabel(pr.review_state)}
                  </Badge>
                )}
                {pr.github_review_state === "APPROVED" && (
                  <Badge variant="success" className="text-[10px] gap-0.5">
                    <Check className="h-2.5 w-2.5" />
                    approved
                  </Badge>
                )}
              </div>

              <p className="text-sm font-medium truncate">{pr.title || "Untitled"}</p>

              <div className="flex items-center gap-2 mt-0.5 text-xs text-prism-text-muted">
                {pr.author && <span>{pr.author}</span>}
                {pr.merged_at && (
                  <span className="flex items-center gap-0.5">
                    <Calendar className="h-2.5 w-2.5" />
                    merged {formatDate(pr.merged_at)}
                  </span>
                )}
                <span className="font-mono text-[10px]">
                  {pr.base_branch} ← {pr.head_branch}
                </span>
              </div>
            </div>
          </div>

          {/* Diff stats */}
          <div className="flex items-center gap-1 text-xs shrink-0">
            <span className="text-prism-success flex items-center gap-0.5">
              <Plus className="h-2.5 w-2.5" />
              {pr.additions}
            </span>
            <span className="text-prism-danger flex items-center gap-0.5">
              <Minus className="h-2.5 w-2.5" />
              {pr.deletions}
            </span>
            <span className="text-prism-text-muted">{pr.changed_files} files</span>
          </div>
        </div>

        {/* Action buttons */}
        {(canApprove || approveMsg) && (
          <div className="flex items-center gap-2 mt-2 pt-2 border-t border-blue-500/20">
            {canApprove && !approveMsg && (
              <Button size="sm" variant="default" className="h-7 text-xs" onClick={handleApprove} disabled={approving}>
                {approving ? (
                  <>
                    <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    Approving…
                  </>
                ) : (
                  <>
                    <Check className="h-3 w-3 mr-1" />
                    Approve on GitHub
                  </>
                )}
              </Button>
            )}
            {approveMsg && (
              <div className={cn("flex items-center gap-1.5 text-xs", approveSuccess ? "text-prism-success" : "text-prism-danger")}>
                {approveSuccess ? <Check className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                {approveMsg}
              </div>
            )}
            {!githubConfigured && (
              <span className="text-[10px] text-prism-text-muted flex items-center gap-1">
                <AlertCircle className="h-2.5 w-2.5" />
                Set GITHUB_TOKEN to enable approval
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
