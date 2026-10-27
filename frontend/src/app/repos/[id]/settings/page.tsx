"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  GitBranch,
  ShieldCheck,
  Brain,
  Plug,
  Database,
  Settings as SettingsIcon,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api, type SettingsResponse } from "@/lib/api";

export default function SettingsPage() {
  const params = useParams();
  const repoId = params.id as string;
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading || !settings) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="text-sm text-prism-text-muted animate-pulse">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <SettingsIcon className="h-5 w-5" />
          Settings & Integrations
        </h1>
        <p className="text-sm text-prism-text-muted mt-1">
          Configure LLM providers, scanner integrations, and review policies
        </p>
      </div>

      {/* LLM Configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-4 w-4" />
            LLM Provider
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Row label="Provider" value={settings.llm.provider} />
          <Row label="Model" value={settings.llm.model} />
          <Row label="Base URL" value={settings.llm.base_url} mono />
          <div className="flex items-center justify-between">
            <span className="text-sm text-prism-text-muted">Status</span>
            <Badge variant={settings.llm.is_available ? "success" : "error"}>
              {settings.llm.is_available ? "Available" : "Not available"}
            </Badge>
          </div>
          {!settings.llm.is_available && (
            <p className="text-xs text-prism-warning">
              Ollama is not running or the model is not installed. PRISM will use fallback
              deterministic analysis without natural-language explanations.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Database */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Database
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Row label="Type" value={settings.database_type} />
        </CardContent>
      </Card>

      {/* Integrations */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plug className="h-4 w-4" />
            Integrations
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {settings.integrations.map(integration => (
            <div
              key={integration.name}
              className="flex items-center justify-between rounded-md border border-border bg-card/50 px-3 py-2"
            >
              <div className="flex items-center gap-2">
                {integration.type === "scanner" ? (
                  <ShieldCheck className="h-4 w-4 text-prism-text-muted" />
                ) : (
                  <GitBranch className="h-4 w-4 text-prism-text-muted" />
                )}
                <div>
                  <p className="text-sm font-medium capitalize">{integration.name}</p>
                  <p className="text-xs text-prism-text-muted capitalize">{integration.type}</p>
                </div>
              </div>
              <Badge variant={integration.configured ? "success" : "secondary"}>
                {integration.status.replace(/_/g, " ")}
              </Badge>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Review Policies */}
      <Card>
        <CardHeader>
          <CardTitle>Review Policies</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-prism-text-muted">
          <p>
            Review states are determined by deterministic rules, not by LLM output.
            The following states are supported:
          </p>
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2 mt-2">
            {[
              ["READY_FOR_POLICY_REVIEW", "All checks passed, eligible for approval"],
              ["REVIEW_REQUIRED", "Manual review needed"],
              ["BLOCKED_BY_FINDING", "High-severity finding blocks approval"],
              ["ANALYSIS_INCOMPLETE", "Indexing or analysis not finished"],
              ["FAILED_CHECKS", "CI/tests/scanners failed"],
              ["HUMAN_SECURITY_REVIEW_REQUIRED", "Security-sensitive change needs human review"],
            ].map(([state, desc]) => (
              <div key={state} className="rounded-md border border-border bg-card/50 px-3 py-2">
                <p className="text-xs font-medium font-mono">{state}</p>
                <p className="text-xs mt-0.5">{desc}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-prism-text-muted">{label}</span>
      <span className={`text-sm ${mono ? "font-mono text-xs" : ""}`}>{value}</span>
    </div>
  );
}
