"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ReviewReport } from "@/lib/api";
import { FileCode, Link2, GitCommit, AlertCircle, Microscope } from "lucide-react";

interface TechnicalEvidenceViewProps {
  report: ReviewReport;
}

interface ChangedFileItem {
  path: string;
  status: string;
  additions: number;
  deletions: number;
  language?: string | null;
  symbols_changed?: number;
}

interface ChangedSymbolItem {
  name: string;
  file: string;
  lines: [number, number];
  change_type: string;
  signature?: string | null;
  has_before?: boolean;
}

interface EvidenceItem {
  file_path: string;
  line_range: [number, number];
  commit?: string;
  source_type: string;
  description: string;
  snippet_preview?: string | null;
}

/**
 * Technical evidence view — detailed evidence for engineers.
 * File paths, line ranges, commit refs, changed symbols, code snippets,
 * callers/callees, scanner IDs, test results, analysis scope, limitations,
 * confidence rationale, and suggested verification steps.
 */
export function TechnicalEvidenceView({ report }: TechnicalEvidenceViewProps) {
  const evidence = report.technical_evidence as Record<string, unknown>;
  const changedFiles = (evidence.changed_files as ChangedFileItem[]) || [];
  const changedSymbols = (evidence.changed_symbols as ChangedSymbolItem[]) || [];
  const evidenceItems = (evidence.evidence_items as EvidenceItem[]) || [];
  const diffStats = (evidence.diff_stats as Record<string, number>) || {};
  const coverage = report.analysis_coverage as Record<string, unknown>;
  const limitations = (evidence.limitations as string[]) || [];

  return (
    <div className="mt-4 space-y-4">
      {/* Diff stats */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCommit className="h-4 w-4" />
            Diff Statistics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            <Stat label="Files changed" value={diffStats.files_changed || 0} />
            <Stat label="Additions" value={diffStats.additions || 0} color="text-prism-success" />
            <Stat label="Deletions" value={diffStats.deletions || 0} color="text-prism-danger" />
          </div>
          <div className="mt-3 text-xs text-prism-text-muted font-mono">
            {String(evidence.base_commit || report.base_sha).substring(0, 12)} → {String(evidence.head_commit || report.commit_sha).substring(0, 12)}
          </div>
        </CardContent>
      </Card>

      {/* Changed files */}
      {changedFiles.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode className="h-4 w-4" />
              Changed Files
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {changedFiles.map((file, i) => (
              <div key={i} className="flex items-center justify-between rounded-md border border-border bg-card/50 px-3 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  <Badge
                    variant={file.status === "added" ? "success" : file.status === "deleted" ? "error" : "secondary"}
                    className="text-xs shrink-0"
                  >
                    {file.status}
                  </Badge>
                  <span className="font-mono text-xs truncate">{file.path}</span>
                </div>
                <span className="text-xs text-prism-text-muted shrink-0">
                  +{file.additions}/-{file.deletions}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Changed symbols */}
      {changedSymbols.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Microscope className="h-4 w-4" />
              Changed Symbols
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {changedSymbols.map((sym, i) => (
              <div key={i} className="rounded-md border border-border bg-card/50 p-2">
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline" className="text-xs">
                    {sym.change_type}
                  </Badge>
                  <span className="text-sm font-medium">{sym.name}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-prism-text-muted">
                  <span className="font-mono">{sym.file}:{sym.lines[0]}-{sym.lines[1]}</span>
                </div>
                {sym.signature && (
                  <pre className="mt-2 text-xs font-mono text-prism-text-muted bg-prism-bg/50 rounded p-2 overflow-x-auto">
                    {sym.signature}
                  </pre>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Evidence items */}
      {evidenceItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Link2 className="h-4 w-4" />
              Evidence References ({evidenceItems.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {evidenceItems.map((item, i) => (
              <div key={i} className="rounded-md border border-border bg-card/50 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="secondary" className="text-xs">
                    {item.source_type}
                  </Badge>
                  <span className="font-mono text-xs">
                    {item.file_path}:{item.line_range[0]}-{item.line_range[1]}
                  </span>
                  <span className="text-xs text-prism-text-muted font-mono ml-auto">
                    {String(item.commit || "").substring(0, 12)}
                  </span>
                </div>
                <p className="text-xs text-prism-text-muted mb-2">{item.description}</p>
                {item.snippet_preview && (
                  <pre className="text-xs font-mono text-prism-text-muted bg-prism-bg/50 rounded p-2 overflow-x-auto max-h-32">
                    {item.snippet_preview}
                  </pre>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Analysis scope */}
      <Card>
        <CardHeader>
          <CardTitle>Analysis Scope & Limitations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-prism-text-muted">
            {String(evidence.analysis_scope || "Analysis scope not recorded.")}
          </p>
          {limitations.map((limit, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <AlertCircle className="h-4 w-4 text-prism-warning mt-0.5 shrink-0" />
              <span className="text-prism-text-muted">{limit}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Coverage */}
      <Card>
        <CardHeader>
          <CardTitle>Analysis Coverage</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Files analyzed" value={Number(coverage.files_analyzed) || 0} />
            <Stat label="Symbols analyzed" value={Number(coverage.symbols_analyzed) || 0} />
            <Stat label="Evidence items" value={Number(coverage.evidence_items) || 0} />
            <Stat label="Tests found" value={Number(coverage.tests_found) || 0} />
            <Stat label="Config changes" value={Number(coverage.config_changes) || 0} />
            <div className="rounded-md border border-border bg-card/50 px-4 py-2">
              <p className="text-xs text-prism-text-muted">Scanner results</p>
              <p className="mt-1 text-sm font-medium">
                {coverage.scanner_results_available ? "Available" : "Not available"}
              </p>
            </div>
          </div>
          {Array.isArray(coverage.incomplete_items) && (coverage.incomplete_items as string[]).length > 0 && (
            <div className="mt-4 pt-3 border-t border-border">
              <p className="text-xs text-prism-text-muted mb-2">Incomplete items:</p>
              <div className="flex flex-wrap gap-1.5">
                {(coverage.incomplete_items as string[]).map((item, i) => (
                  <Badge key={i} variant="warning" className="text-xs">{item}</Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="rounded-md border border-border bg-card/50 px-4 py-2">
      <p className="text-xs text-prism-text-muted">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${color || ""}`}>{value}</p>
    </div>
  );
}
