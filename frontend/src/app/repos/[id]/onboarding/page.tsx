"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { CheckCircle2, AlertCircle, Loader2, XCircle, ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { api, type IngestionStatus, type Repository } from "@/lib/api";

export default function OnboardingPage() {
  const params = useParams();
  const router = useRouter();
  const repoId = params.id as string;
  const [repo, setRepo] = useState<Repository | null>(null);
  const [status, setStatus] = useState<IngestionStatus | null>(null);
  const [polling, setPolling] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.getIngestionStatus(repoId);
      setStatus(s);
      if (s.status === "completed" || s.status === "failed") {
        setPolling(false);
      }
    } catch {
      // Might not be ready yet
    }
  }, [repoId]);

  useEffect(() => {
    api.getRepo(repoId).then(setRepo).catch(() => {});
    fetchStatus();
  }, [repoId, fetchStatus]);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, [polling, fetchStatus]);

  const steps = [
    { key: "clone", label: "Creating persistent Git mirror", done: status?.commit_sha != null },
    { key: "analyze", label: "Analyzing repository structure", done: (status?.languages_detected != null && Object.keys(status.languages_detected).length > 0) },
    { key: "index", label: "Indexing files and symbols", done: (status?.files_indexed ?? 0) > 0 },
    { key: "symbols", label: "Extracting call relationships", done: (status?.symbols_indexed ?? 0) > 0 },
    { key: "complete", label: "Building repository overview", done: status?.status === "completed" },
  ];

  const isComplete = status?.status === "completed";
  const isFailed = status?.status === "failed";

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold">Repository Onboarding</h1>
        <p className="text-sm text-prism-text-muted mt-1">
          {repo?.full_name || "Loading..."} — Processing repository for analysis
        </p>
      </div>

      {/* Progress bar */}
      <Card className="mb-6">
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium">
              {isComplete ? "Ingestion complete" : isFailed ? "Ingestion failed" : "Processing..."}
            </span>
            <Badge variant={isComplete ? "success" : isFailed ? "error" : "info"}>
              {status?.status || "starting"}
            </Badge>
          </div>
          <Progress value={status?.progress || 0} className="mb-4" />

          {status?.commit_sha && (
            <div className="text-xs text-prism-text-muted font-mono">
              Commit: {status.commit_sha.substring(0, 12)}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Steps */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Ingestion Steps</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {steps.map((step, i) => {
            const isDone = step.done;
            const isCurrent = !isDone && steps.slice(0, i).every(s => s.done);
            return (
              <div key={step.key} className="flex items-center gap-3">
                {isDone ? (
                  <CheckCircle2 className="h-5 w-5 text-prism-success" />
                ) : isCurrent && !isFailed ? (
                  <Loader2 className="h-5 w-5 text-prism-mint animate-spin" />
                ) : isFailed ? (
                  <XCircle className="h-5 w-5 text-prism-danger" />
                ) : (
                  <div className="h-5 w-5 rounded-full border-2 border-border" />
                )}
                <span className={`text-sm ${isDone ? "text-foreground" : "text-prism-text-muted"}`}>
                  {step.label}
                </span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Languages detected */}
      {status?.languages_detected && Object.keys(status.languages_detected).length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Detected Languages</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(status.languages_detected).map(([lang, count]) => (
                <Badge key={lang} variant="secondary">
                  {lang} · {count} files
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stats */}
      {((status?.files_indexed ?? 0) > 0 || (status?.symbols_indexed ?? 0) > 0) && (
        <div className="grid grid-cols-2 gap-4 mb-6">
          <StatBox label="Files Indexed" value={status?.files_indexed || 0} />
          <StatBox label="Symbols Extracted" value={status?.symbols_indexed || 0} />
        </div>
      )}

      {/* Errors */}
      {status?.errors && status.errors.length > 0 && (
        <Card className="mb-6 border-prism-danger/30">
          <CardHeader>
            <CardTitle className="text-prism-danger">Errors</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {status.errors.map((err, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <AlertCircle className="h-4 w-4 text-prism-danger mt-0.5 shrink-0" />
                <span className="text-prism-text-muted">{err}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Warnings */}
      {status?.warnings && status.warnings.length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Warnings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {status.warnings.map((warn, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <AlertCircle className="h-4 w-4 text-prism-warning mt-0.5 shrink-0" />
                <span className="text-prism-text-muted">{warn}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Action buttons */}
      {isComplete && (
        <div className="flex gap-3">
          <Button onClick={() => router.push(`/repos/${repoId}`)}>
            View Dashboard
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      )}
      {isFailed && (
        <Button
          variant="outline"
          onClick={() => {
            setPolling(true);
            fetchStatus();
          }}
        >
          Retry Ingestion
        </Button>
      )}
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border bg-card px-4 py-3">
      <p className="text-xs text-prism-text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value.toLocaleString()}</p>
    </div>
  );
}
