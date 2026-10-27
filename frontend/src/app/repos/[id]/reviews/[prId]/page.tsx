"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ShieldCheck,
  AlertTriangle,
  FileCode,
  GitCommit,
  CheckCircle2,
  XCircle,
  Info,
  Eye,
  Brain,
  Link2,
  ArrowLeft,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, type ReviewReport } from "@/lib/api";
import {
  reviewStateColor,
  reviewStateLabel,
  severityColor,
  shortSha,
  formatDate,
  cn,
} from "@/lib/utils";
import { ExecutiveView } from "@/components/ExecutiveView";
import { TechnicalEvidenceView } from "@/components/TechnicalEvidenceView";

export default function PrReviewPage() {
  const params = useParams();
  const repoId = params.id as string;
  const prId = params.prId as string;
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(true);

  useEffect(() => {
    const fetchReport = async () => {
      try {
        const r = await api.getReviewReport(repoId, prId);
        setReport(r);
        if (r.review_state !== "analysis_incomplete") {
          setPolling(false);
        }
      } catch (e) {
        if (e instanceof Error && e.message.includes("404")) {
          // Report not ready yet — keep polling
        } else {
          setError(e instanceof Error ? e.message : "Failed to load review");
          setPolling(false);
        }
      } finally {
        setLoading(false);
      }
    };
    fetchReport();
  }, [repoId, prId]);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(async () => {
      try {
        const r = await api.getReviewReport(repoId, prId);
        setReport(r);
        if (r.review_state !== "analysis_incomplete") {
          setPolling(false);
        }
      } catch {
        // Keep polling
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [polling, repoId, prId]);

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="text-sm text-prism-text-muted animate-pulse">
          {polling ? "Analyzing pull request..." : "Loading review..."}
        </div>
      </div>
    );
  }

  if (error || (!report && !polling)) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="text-sm text-prism-danger">{error || "No review report found."}</div>
        <Button variant="outline" className="mt-4" onClick={() => history.back()}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="flex items-center gap-3 text-sm text-prism-text-muted">
          <div className="h-4 w-4 rounded-full border-2 border-prism-mint border-t-transparent animate-spin" />
          Analysis in progress. This may take a minute...
        </div>
      </div>
    );
  }

  const stateColor = reviewStateColor(report.review_state);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => history.back()}
            className="text-prism-text-muted"
          >
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back
          </Button>
        </div>
        <h1 className="text-xl font-semibold">Pull Request Review</h1>
        <div className="flex items-center gap-4 mt-2 text-sm text-prism-text-muted">
          <span className="flex items-center gap-1">
            <GitCommit className="h-3.5 w-3.5" />
            <span className="font-mono text-xs">{shortSha(report.base_sha)} → {shortSha(report.commit_sha)}</span>
          </span>
          <span>{formatDate(report.created_at)}</span>
          {report.llm_model && (
            <Badge variant="secondary" className="text-xs">
              <Brain className="mr-1 h-3 w-3" />
              {report.llm_model}
            </Badge>
          )}
        </div>
      </div>

      {/* Review state banner */}
      <div
        className="rounded-md border p-4 flex items-start gap-3"
        style={{
          borderColor: `${stateColor}40`,
          backgroundColor: `${stateColor}10`,
        }}
      >
        <ShieldCheck className="h-5 w-5 shrink-0 mt-0.5" style={{ color: stateColor }} />
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-sm font-semibold" style={{ color: stateColor }}>
              {reviewStateLabel(report.review_state)}
            </h2>
            {report.is_stale && (
              <Badge variant="warning" className="text-xs">STALE ANALYSIS</Badge>
            )}
          </div>
          <p className="text-sm text-prism-text-muted">
            {report.recommended_action}
          </p>
        </div>
      </div>

      {/* Change summary */}
      <Card>
        <CardHeader>
          <CardTitle>What Changed</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed">{report.change_summary}</p>
          {report.functional_purpose && (
            <div className="mt-4 pt-4 border-t border-border">
              <p className="text-xs font-medium text-prism-text-muted mb-1">Functional Purpose</p>
              <p className="text-sm leading-relaxed">{report.functional_purpose}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Affected components */}
      {report.affected_components.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode className="h-4 w-4" />
              Affected Components ({report.affected_components.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {report.affected_components.map((comp, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-md border border-border bg-card/50 px-3 py-2"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Badge
                      variant={comp.status === "added" ? "success" : comp.status === "deleted" ? "error" : "secondary"}
                      className="text-xs shrink-0"
                    >
                      {comp.status}
                    </Badge>
                    <span className="font-mono text-xs truncate">{comp.file_path}</span>
                  </div>
                  {comp.symbols_changed > 0 && (
                    <span className="text-xs text-prism-text-muted shrink-0">
                      {comp.symbols_changed} symbols
                    </span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Findings */}
      {report.findings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Findings ({report.findings.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {report.findings.map((finding, i) => (
              <div key={finding.id || i} className="rounded-md border border-border bg-card/50 p-3">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <div
                      className="prism-status-dot"
                      style={{ backgroundColor: severityColor(finding.severity) }}
                    />
                    <span className="text-sm font-medium">{finding.title}</span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Badge
                      variant="secondary"
                      className="text-xs"
                      style={{ color: severityColor(finding.severity) }}
                    >
                      {finding.severity}
                    </Badge>
                    <Badge
                      variant={
                        finding.confidence === "confirmed" ? "success" :
                        finding.confidence === "likely" ? "warning" :
                        "outline"
                      }
                      className="text-xs"
                    >
                      {finding.confidence}
                    </Badge>
                    {finding.is_blocking && (
                      <Badge variant="error" className="text-xs">BLOCKING</Badge>
                    )}
                  </div>
                </div>
                <p className="text-sm text-prism-text-muted leading-relaxed">
                  {finding.description}
                </p>
                {finding.file_path && (
                  <div className="mt-2 flex items-center gap-1.5 text-xs text-prism-text-muted">
                    <Link2 className="h-3 w-3" />
                    <span className="font-mono">
                      {finding.file_path}
                      {finding.line_range.length > 0 && `:${finding.line_range[0]}-${finding.line_range[1]}`}
                    </span>
                  </div>
                )}
                {finding.evidence && finding.evidence.length > 0 && (
                  <div className="mt-2 pl-4 border-l-2 border-border space-y-1">
                    {finding.evidence.map((ev, j) => (
                      <div key={j} className="text-xs text-prism-text-muted">
                        <Link2 className="inline h-3 w-3 mr-1" />
                        <span className="font-mono">{ev.file_path}:{ev.line_range[0]}</span>
                        <span className="ml-2">[{ev.source}]</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Potential security impacts */}
      {report.potential_security_impacts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              Potential Security Impacts
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {report.potential_security_impacts.map((impact, i) => (
              <div key={i} className="rounded-md border border-border bg-card/50 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Badge
                    variant="secondary"
                    className="text-xs"
                    style={{ color: severityColor(impact.severity) }}
                  >
                    {impact.severity}
                  </Badge>
                  <Badge
                    variant={impact.confidence === "confirmed" ? "success" : "outline"}
                    className="text-xs"
                  >
                    {impact.confidence}
                  </Badge>
                </div>
                <p className="text-sm text-prism-text-muted leading-relaxed">
                  {impact.description}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Required checks */}
      {report.required_checks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" />
              Required Checks
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {report.required_checks.map((check, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-md border border-border bg-card/50 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  {check.status === "passed" ? (
                    <CheckCircle2 className="h-4 w-4 text-prism-success" />
                  ) : check.status === "failed" ? (
                    <XCircle className="h-4 w-4 text-prism-danger" />
                  ) : (
                    <Info className="h-4 w-4 text-prism-warning" />
                  )}
                  <span className="text-sm">{check.name}</span>
                  <Badge variant="outline" className="text-xs">{check.source}</Badge>
                </div>
                <span
                  className={cn(
                    "text-xs",
                    check.status === "passed" ? "text-prism-success" :
                    check.status === "failed" ? "text-prism-danger" :
                    "text-prism-warning"
                  )}
                >
                  {check.status}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Detailed views toggle */}
      <Tabs defaultValue="executive">
        <TabsList className="w-full">
          <TabsTrigger value="executive" className="flex-1">
            <Eye className="mr-1.5 h-4 w-4" />
            Simple Explanation
          </TabsTrigger>
          <TabsTrigger value="technical" className="flex-1">
            <FileCode className="mr-1.5 h-4 w-4" />
            Technical Evidence
          </TabsTrigger>
        </TabsList>
        <TabsContent value="executive">
          <ExecutiveView report={report} />
        </TabsContent>
        <TabsContent value="technical">
          <TechnicalEvidenceView report={report} />
        </TabsContent>
      </Tabs>

      {/* Uncertainty */}
      {report.uncertainty && (
        <Card className="border-prism-warning/20">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-prism-warning">
              <AlertTriangle className="h-4 w-4" />
              Uncertainty & Limitations
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-prism-text-muted leading-relaxed">
              {report.uncertainty}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
