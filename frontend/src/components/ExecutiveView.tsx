"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ReviewReport } from "@/lib/api";
import { CheckCircle2, XCircle, Info, AlertTriangle, HelpCircle } from "lucide-react";

interface ExecutiveViewProps {
  report: ReviewReport;
}

/**
 * Executive view — plain-English explanation for non-technical reviewers.
 * Avoids unexplained acronyms. Explains consequences, not just vulnerability class names.
 */
export function ExecutiveView({ report }: ExecutiveViewProps) {
  const summary = report.executive_summary as Record<string, string>;
  const checks = report.required_checks || [];
  const passed = checks.filter(c => c.status === "passed");
  const failed = checks.filter(c => c.status === "failed");
  const incomplete = checks.filter(c => c.status === "incomplete" || c.status === "unknown" || c.status === "missing");

  const getStr = (key: string, fallback: string): string => {
    const val = summary[key];
    return typeof val === "string" ? val : fallback;
  };

  const sections: Array<{ key: string; title: string; value: string; isBadge?: boolean }> = [
    {
      key: "what_changed",
      title: "What changed?",
      value: getStr("what_changed", report.change_summary),
    },
    {
      key: "why_made",
      title: "Why was this change made?",
      value: getStr("why_made", "The available evidence does not fully explain the motivation for this change."),
    },
    {
      key: "what_feature_does",
      title: "What does the affected feature do?",
      value: getStr("what_feature_does", report.functional_purpose || "Feature purpose not determined from available evidence."),
    },
    {
      key: "what_could_go_wrong",
      title: "What could go wrong?",
      value: getStr("what_could_go_wrong", "No specific risk identified by the analysis."),
    },
    {
      key: "who_affected",
      title: "Who or what could be affected?",
      value: getStr("who_affected", "Users and systems that depend on the changed components."),
    },
    {
      key: "evidence_quality",
      title: "How strong is the evidence?",
      value: getStr("evidence_quality", "insufficient"),
      isBadge: true,
    },
    {
      key: "confidence",
      title: "How confident is this analysis?",
      value: getStr("confidence", "low"),
      isBadge: true,
    },
  ];

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Info className="h-4 w-4 text-prism-mint" />
          Executive Summary
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <p className="text-sm text-prism-text-muted leading-relaxed">
          This section explains the change in plain English for reviewers who may not be deeply technical.
          It does not assert that the change is safe or unsafe — it describes what the evidence shows.
        </p>

        {sections.map(section => (
          <div key={section.key} className="border-l-2 border-border pl-4">
            <p className="text-sm font-medium mb-1">{section.title}</p>
            {section.isBadge ? (
              <Badge
                variant={
                  section.value === "high" || section.value === "strong" ? "success" :
                  section.value === "moderate" || section.value === "medium" ? "warning" :
                  "secondary"
                }
              >
                {section.value}
              </Badge>
            ) : (
              <p className="text-sm text-prism-text-muted leading-relaxed">
                {section.value}
              </p>
            )}
          </div>
        ))}

        {/* Checks summary */}
        <div className="border-t border-border pt-4 space-y-2">
          <p className="text-sm font-medium">Checks Summary</p>
          <div className="flex flex-wrap gap-2">
            {passed.length > 0 && (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 className="h-3 w-3" />
                {passed.length} passed
              </Badge>
            )}
            {failed.length > 0 && (
              <Badge variant="error" className="gap-1">
                <XCircle className="h-3 w-3" />
                {failed.length} failed
              </Badge>
            )}
            {incomplete.length > 0 && (
              <Badge variant="warning" className="gap-1">
                <HelpCircle className="h-3 w-3" />
                {incomplete.length} incomplete
              </Badge>
            )}
          </div>
        </div>

        {/* Reviewer action */}
        {summary.reviewer_action && (
          <div className="border-t border-border pt-4">
            <div className="flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-prism-mint shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium mb-1">What should the reviewer do?</p>
                <p className="text-sm text-prism-text-muted leading-relaxed">
                  {getStr("reviewer_action", "")}
                </p>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
