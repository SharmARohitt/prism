import { describe, it, expect } from "vitest";
import {
  cn,
  formatDate,
  formatDateTime,
  shortSha,
  severityColor,
  reviewStateColor,
  reviewStateLabel,
} from "../utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("px-2", "py-1")).toBe("px-2 py-1");
  });

  it("handles conditional classes", () => {
    expect(cn("base", { active: true, disabled: false })).toBe("base active");
  });

  it("deduplicates conflicting tailwind classes", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});

describe("formatDate", () => {
  it("formats a date string", () => {
    const result = formatDate("2024-01-15T10:00:00Z");
    expect(result).toMatch(/2024/);
    expect(result).toMatch(/Jan/);
  });

  it("returns dash for null", () => {
    expect(formatDate(null)).toBe("—");
  });

  it("returns dash for empty string", () => {
    expect(formatDate("")).toBe("—");
  });
});

describe("shortSha", () => {
  it("truncates a SHA to 12 characters", () => {
    expect(shortSha("abcdef1234567890abcdef1234567890")).toBe("abcdef123456");
  });

  it("returns dash for null", () => {
    expect(shortSha(null)).toBe("—");
  });

  it("returns dash for undefined", () => {
    expect(shortSha(undefined)).toBe("—");
  });
});

describe("severityColor", () => {
  it("returns red for critical", () => {
    expect(severityColor("critical")).toBe("#f87171");
  });

  it("returns orange for high", () => {
    expect(severityColor("high")).toBe("#fb923c");
  });

  it("returns yellow for medium", () => {
    expect(severityColor("medium")).toBe("#fbbf24");
  });

  it("returns blue for low", () => {
    expect(severityColor("low")).toBe("#60a5fa");
  });

  it("returns gray for unknown", () => {
    expect(severityColor("unknown")).toBe("#64748b");
  });
});

describe("reviewStateColor", () => {
  it("returns green for ready_for_policy_review", () => {
    expect(reviewStateColor("ready_for_policy_review")).toBe("#34d399");
  });

  it("returns yellow for review_required", () => {
    expect(reviewStateColor("review_required")).toBe("#fbbf24");
  });

  it("returns red for blocked_by_finding", () => {
    expect(reviewStateColor("blocked_by_finding")).toBe("#f87171");
  });

  it("returns purple for human_security_review_required", () => {
    expect(reviewStateColor("human_security_review_required")).toBe("#c084fc");
  });
});

describe("reviewStateLabel", () => {
  it("returns human-readable label", () => {
    expect(reviewStateLabel("ready_for_policy_review")).toBe("Ready for Policy Review");
    expect(reviewStateLabel("blocked_by_finding")).toBe("Blocked by Finding");
    expect(reviewStateLabel("analysis_incomplete")).toBe("Analysis Incomplete");
  });

  it("returns input for unknown state", () => {
    expect(reviewStateLabel("unknown_state")).toBe("unknown_state");
  });
});
