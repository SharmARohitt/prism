import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date | null): string {
  if (!date) return "—";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(date: string | Date | null): string {
  if (!date) return "—";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortSha(sha: string | null | undefined): string {
  if (!sha) return "—";
  return sha.substring(0, 12);
}

export function severityColor(severity: string): string {
  const colors: Record<string, string> = {
    critical: "#f87171",
    high: "#fb923c",
    medium: "#fbbf24",
    low: "#60a5fa",
    info: "#64748b",
  };
  return colors[severity] || "#64748b";
}

export function reviewStateColor(state: string): string {
  const colors: Record<string, string> = {
    ready_for_policy_review: "#34d399",
    review_required: "#fbbf24",
    blocked_by_finding: "#f87171",
    analysis_incomplete: "#64748b",
    failed_checks: "#fb923c",
    human_security_review_required: "#c084fc",
  };
  return colors[state] || "#64748b";
}

export function reviewStateLabel(state: string): string {
  const labels: Record<string, string> = {
    ready_for_policy_review: "Ready for Policy Review",
    review_required: "Review Required",
    blocked_by_finding: "Blocked by Finding",
    analysis_incomplete: "Analysis Incomplete",
    failed_checks: "Failed Checks",
    human_security_review_required: "Human Security Review Required",
  };
  return labels[state] || state;
}
