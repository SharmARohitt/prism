"use client";

import { useEffect, useState } from "react";
import {
  X,
  FileCode,
  Shield,
  GitCommit,
  ArrowDownLeft,
  ArrowUpRight,
  AlertTriangle,
  Info,
  ChevronRight,
  Loader2,
  Link2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { NodeDetails, NodeRelationship } from "@/lib/graphTypes";
import { NODE_TYPE_META, EDGE_TYPE_META, EVIDENCE_META } from "@/lib/graphTypes";
import { cn } from "@/lib/utils";

interface NodeDetailsPanelProps {
  repoId: string;
  nodeId: string | null;
  onClose: () => void;
  onNavigate: (nodeId: string) => void;
}

type PanelTab = "simple" | "technical" | "evidence";

export function NodeDetailsPanel({
  repoId,
  nodeId,
  onClose,
  onNavigate,
}: NodeDetailsPanelProps) {
  const [details, setDetails] = useState<NodeDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<PanelTab>("simple");

  useEffect(() => {
    if (!nodeId) {
      setDetails(null);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .getNodeDetails(repoId, nodeId)
      .then((d) => setDetails(d))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load node details"))
      .finally(() => setLoading(false));
  }, [repoId, nodeId]);

  if (!nodeId) return null;

  const typeMeta = details
    ? (NODE_TYPE_META[details.type] ?? NODE_TYPE_META["file"])
    : null;

  return (
    <div
      className="absolute right-0 top-0 h-full w-80 z-20 flex flex-col border-l overflow-hidden"
      style={{
        backgroundColor: "#090d12",
        borderColor: "#1a1f28",
        boxShadow: "-4px 0 24px rgba(0,0,0,0.6)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: "#1a1f28" }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {typeMeta && (
            <span
              className="text-xs w-5 h-5 flex items-center justify-center rounded shrink-0"
              style={{
                backgroundColor: `${typeMeta.color}20`,
                color: typeMeta.color,
              }}
            >
              {typeMeta.icon}
            </span>
          )}
          <span className="text-sm font-semibold truncate text-slate-200">
            {loading ? "Loading…" : details?.label ?? "Component"}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-slate-300 transition-colors shrink-0 ml-2"
          aria-label="Close panel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading && (
        <div className="flex items-center justify-center flex-1">
          <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
        </div>
      )}

      {error && (
        <div className="p-4 text-sm text-red-400 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      {details && !loading && (
        <>
          {/* Tab row */}
          <div
            className="flex border-b shrink-0"
            style={{ borderColor: "#1a1f28" }}
          >
            {(["simple", "technical", "evidence"] as PanelTab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "flex-1 py-2 text-xs font-medium capitalize transition-colors",
                  tab === t
                    ? "text-teal-400 border-b-2 border-teal-400"
                    : "text-slate-500 hover:text-slate-300",
                )}
              >
                {t === "simple" ? "Explain" : t === "technical" ? "Technical" : "Evidence"}
              </button>
            ))}
          </div>

          {/* Scrollable body */}
          <div className="flex-1 overflow-y-auto no-scrollbar">
            {tab === "simple" && <SimpleTab details={details} onNavigate={onNavigate} />}
            {tab === "technical" && <TechnicalTab details={details} onNavigate={onNavigate} />}
            {tab === "evidence" && <EvidenceTab details={details} />}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Simple tab ─────────────────────────────────────────── */

function SimpleTab({
  details,
  onNavigate,
}: {
  details: NodeDetails;
  onNavigate: (id: string) => void;
}) {
  const typeMeta = NODE_TYPE_META[details.type] ?? NODE_TYPE_META["file"];

  return (
    <div className="p-4 space-y-4 text-sm">
      {/* What is this */}
      <Section icon={<Info className="h-3.5 w-3.5" />} title="What is this?">
        <p className="text-slate-300 leading-relaxed">{details.plain_english}</p>
        <div className="flex items-center gap-2 mt-2">
          <Badge
            style={{
              backgroundColor: `${typeMeta.color}20`,
              color: typeMeta.color,
              borderColor: `${typeMeta.color}40`,
            }}
            className="text-[10px] border"
          >
            {typeMeta.label}
          </Badge>
          {details.is_security_sensitive && (
            <Badge className="text-[10px] bg-red-500/10 text-red-400 border border-red-500/30">
              Security-sensitive
            </Badge>
          )}
        </div>
      </Section>

      {/* What uses it */}
      {details.incoming_count > 0 && (
        <Section
          icon={<ArrowDownLeft className="h-3.5 w-3.5 text-blue-400" />}
          title={`Used by (${details.incoming_count})`}
        >
          {details.what_uses_it.length > 0 ? (
            <ul className="space-y-1">
              {details.what_uses_it.map((item, i) => (
                <li key={i} className="text-slate-400 text-xs flex items-start gap-1">
                  <ChevronRight className="h-3 w-3 mt-0.5 shrink-0 text-slate-600" />
                  {item}
                </li>
              ))}
              {details.incoming_count > details.what_uses_it.length && (
                <li className="text-slate-600 text-xs">
                  +{details.incoming_count - details.what_uses_it.length} more
                </li>
              )}
            </ul>
          ) : (
            <p className="text-slate-600 text-xs">No direct callers detected.</p>
          )}
        </Section>
      )}

      {/* What it uses */}
      {details.outgoing_count > 0 && (
        <Section
          icon={<ArrowUpRight className="h-3.5 w-3.5 text-teal-400" />}
          title={`Depends on (${details.outgoing_count})`}
        >
          {details.what_it_uses.length > 0 ? (
            <ul className="space-y-1">
              {details.what_it_uses.map((item, i) => (
                <li key={i} className="text-slate-400 text-xs flex items-start gap-1">
                  <ChevronRight className="h-3 w-3 mt-0.5 shrink-0 text-slate-600" />
                  {item}
                </li>
              ))}
              {details.outgoing_count > details.what_it_uses.length && (
                <li className="text-slate-600 text-xs">
                  +{details.outgoing_count - details.what_it_uses.length} more
                </li>
              )}
            </ul>
          ) : (
            <p className="text-slate-600 text-xs">No outgoing dependencies detected.</p>
          )}
        </Section>
      )}

      {/* Potential impact */}
      <Section
        icon={<AlertTriangle className="h-3.5 w-3.5 text-amber-400" />}
        title="What could be affected?"
      >
        <p className="text-slate-400 leading-relaxed text-xs">{details.impact}</p>
      </Section>
    </div>
  );
}

/* ── Technical tab ──────────────────────────────────────── */

function TechnicalTab({
  details,
  onNavigate,
}: {
  details: NodeDetails;
  onNavigate: (id: string) => void;
}) {
  return (
    <div className="p-4 space-y-4 text-sm">
      {/* File location */}
      {details.file_path && (
        <Section icon={<FileCode className="h-3.5 w-3.5" />} title="Location">
          <code className="text-xs font-mono text-teal-400 break-all">{details.file_path}</code>
          {details.start_line != null && (
            <span className="text-xs text-slate-500 ml-2">
              :{details.start_line}–{details.end_line}
            </span>
          )}
        </Section>
      )}

      {/* Signature */}
      {details.signature && (
        <Section icon={<span className="text-xs text-teal-400">ƒ</span>} title="Signature">
          <pre className="text-xs font-mono text-slate-300 bg-black/30 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
            {details.signature}
          </pre>
        </Section>
      )}

      {/* Incoming relationships */}
      <Section
        icon={<ArrowDownLeft className="h-3.5 w-3.5 text-blue-400" />}
        title={`Incoming (${details.incoming.length})`}
      >
        <RelList rels={details.incoming} onNavigate={onNavigate} />
      </Section>

      {/* Outgoing relationships */}
      <Section
        icon={<ArrowUpRight className="h-3.5 w-3.5 text-teal-400" />}
        title={`Outgoing (${details.outgoing.length})`}
      >
        <RelList rels={details.outgoing} onNavigate={onNavigate} />
      </Section>

      {/* Security */}
      {details.is_security_sensitive && (
        <Section icon={<Shield className="h-3.5 w-3.5 text-red-400" />} title="Security Note">
          <p className="text-red-300 text-xs leading-relaxed">
            This component has a security-sensitive name. It may handle authentication,
            authorization, cryptography, input validation, or data access. Changes should
            be reviewed carefully.
          </p>
        </Section>
      )}

      {/* Commit activity */}
      <Section icon={<GitCommit className="h-3.5 w-3.5" />} title="Activity">
        <div className="space-y-1 text-xs text-slate-500">
          <div className="flex justify-between">
            <span>Changes recorded</span>
            <span className="text-slate-400">{details.change_count}</span>
          </div>
          <div className="flex justify-between">
            <span>Last modified</span>
            <span className="text-slate-400">{details.last_modified ?? "Unknown"}</span>
          </div>
          {details.change_count === 0 && (
            <p className="text-slate-600 text-[10px] pt-1">
              Zero recorded changes does not prove this is unused — dynamic dispatch,
              generated code, or external callers may not be tracked.
            </p>
          )}
        </div>
      </Section>
    </div>
  );
}

/* ── Evidence tab ───────────────────────────────────────── */

function EvidenceTab({ details }: { details: NodeDetails }) {
  return (
    <div className="p-4 space-y-4 text-sm">
      <Section icon={<Link2 className="h-3.5 w-3.5" />} title="Source Evidence">
        {details.evidence.length > 0 ? (
          <ul className="space-y-2">
            {details.evidence.map((e, i) => (
              <li
                key={i}
                className="text-xs text-slate-400 flex items-start gap-2 border-l-2 pl-2"
                style={{ borderColor: "#1a1f28" }}
              >
                <span className="text-teal-600 mt-0.5 shrink-0">●</span>
                {e}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-slate-600 text-xs">No evidence references recorded.</p>
        )}
      </Section>

      <div
        className="rounded-md border p-3 text-xs text-slate-500 leading-relaxed"
        style={{ borderColor: "#1a1f28", backgroundColor: "#0c0f14" }}
      >
        <p className="font-medium text-slate-400 mb-1">Analysis Completeness</p>
        <p>
          This analysis is based on static code parsing. Dynamic relationships, runtime
          behaviour, reflection, and framework-based registration may not be captured.
          All claims link to source evidence above.
        </p>
      </div>
    </div>
  );
}

/* ── Shared sub-components ──────────────────────────────── */

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        {icon}
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

function RelList({
  rels,
  onNavigate,
}: {
  rels: NodeRelationship[];
  onNavigate: (id: string) => void;
}) {
  if (rels.length === 0) {
    return <p className="text-slate-600 text-xs">None detected.</p>;
  }

  return (
    <ul className="space-y-1.5">
      {rels.slice(0, 12).map((rel, i) => {
        const edgeMeta = EDGE_TYPE_META[rel.relation_type] ?? EDGE_TYPE_META["references"];
        const evMeta = EVIDENCE_META[rel.evidence_class];
        const nodeMeta = NODE_TYPE_META[rel.type as keyof typeof NODE_TYPE_META] ?? NODE_TYPE_META["file"];
        return (
          <li
            key={i}
            className="flex items-start gap-2 group cursor-pointer rounded px-1.5 py-1 hover:bg-white/5 transition-colors"
            onClick={() => rel.node_id && onNavigate(rel.node_id)}
          >
            <span
              className="text-[9px] mt-0.5 shrink-0 w-4 h-4 flex items-center justify-center rounded"
              style={{ backgroundColor: `${nodeMeta.color}20`, color: nodeMeta.color }}
            >
              {nodeMeta.icon}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-xs text-slate-300 truncate group-hover:text-white transition-colors">
                  {rel.label}
                </span>
                <span
                  className="text-[9px] px-1 rounded"
                  style={{ backgroundColor: `${edgeMeta.color}20`, color: edgeMeta.color }}
                >
                  {edgeMeta.label}
                </span>
              </div>
              <div className="flex items-center gap-1.5 mt-0.5">
                {rel.file_path && (
                  <span className="text-[10px] text-slate-600 font-mono truncate">
                    {rel.file_path.split("/").pop()}
                    {rel.line_number ? `:${rel.line_number}` : ""}
                  </span>
                )}
                <span className="text-[9px]" style={{ color: evMeta.color }}>
                  {evMeta.label}
                </span>
              </div>
            </div>
          </li>
        );
      })}
      {rels.length > 12 && (
        <li className="text-[10px] text-slate-600 pl-1">+{rels.length - 12} more</li>
      )}
    </ul>
  );
}
