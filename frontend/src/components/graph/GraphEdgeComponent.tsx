"use client";

import { memo, useState } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "reactflow";
import { EDGE_TYPE_META, EVIDENCE_META, type RelationType, type EvidenceClass } from "@/lib/graphTypes";

export type GraphEdgeData = {
  relation_type: RelationType;
  evidence_class: EvidenceClass;
  line_number?: number | null;
  source_file?: string | null;
  target_file?: string | null;
  source_symbol?: string | null;
  target_symbol?: string | null;
  dimmed?: boolean;
  highlighted?: boolean;
};

/**
 * Custom React Flow edge with:
 * - Directional arrow marker
 * - Color-coded by relationship type
 * - Dashed for inferred/unknown relationships
 * - Hover tooltip with plain-English explanation
 * - Evidence classification label
 */
export const GraphEdgeComponent = memo(function GraphEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  markerEnd,
}: EdgeProps<GraphEdgeData>) {
  const [hovered, setHovered] = useState(false);

  const relType = data?.relation_type ?? "references";
  const evClass = data?.evidence_class ?? "unknown";
  const meta = EDGE_TYPE_META[relType] ?? EDGE_TYPE_META["references"];
  const evMeta = EVIDENCE_META[evClass];

  const isDimmed = data?.dimmed && !selected && !hovered;
  const isHighlighted = data?.highlighted || selected || hovered;

  // Compute path
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 6,
  });

  const strokeColor = isDimmed
    ? "#1e2530"
    : isHighlighted
    ? meta.color
    : `${meta.color}77`;

  const strokeWidth = isHighlighted ? 1.5 : 0.75;
  const opacity = isDimmed ? 0.15 : isHighlighted ? 1 : 0.5;

  // Build plain-English edge explanation
  const explanation = buildExplanation(relType, evClass, data);

  return (
    <>
      <defs>
        <marker
          id={`arrow-${id}`}
          viewBox="0 0 8 8"
          refX="6"
          refY="4"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L8,4 L0,8 Z" fill={strokeColor} opacity={opacity} />
        </marker>
      </defs>

      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={`url(#arrow-${id})`}
        style={{
          stroke: strokeColor,
          strokeWidth,
          strokeDasharray: meta.dashed || evClass === "inferred" ? "4 3" : undefined,
          opacity,
          transition: "all 0.15s ease",
          cursor: "pointer",
        }}
        interactionWidth={12}
      />

      {/* Invisible wider hit area for hover */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={14}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{ cursor: "pointer" }}
      />

      {/* Hover tooltip */}
      {hovered && (
        <EdgeLabelRenderer>
          <div
            className="absolute z-50 pointer-events-none"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)` }}
          >
            <div
              className="rounded-md border px-3 py-2 shadow-xl text-xs max-w-[260px]"
              style={{
                backgroundColor: "#0c0f14",
                borderColor: `${meta.color}55`,
                color: "#e2e8f0",
              }}
            >
              {/* Relationship type */}
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                  style={{ backgroundColor: `${meta.color}22`, color: meta.color }}
                >
                  {meta.label}
                </span>
                <span
                  className="text-[10px]"
                  style={{ color: evMeta.color }}
                >
                  {evMeta.label}
                </span>
              </div>

              {/* Plain-English explanation */}
              <p className="text-[11px] text-slate-300 leading-snug">{explanation}</p>

              {/* Source evidence */}
              {data?.source_file && (
                <div className="mt-1.5 pt-1.5 border-t border-slate-800 text-[10px] text-slate-500 font-mono truncate">
                  {data.source_file}
                  {data?.line_number ? `:${data.line_number}` : ""}
                </div>
              )}
            </div>
          </div>
        </EdgeLabelRenderer>
      )}

      {/* Relationship label when selected */}
      {selected && (
        <EdgeLabelRenderer>
          <div
            className="absolute pointer-events-none"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)` }}
          >
            <span
              className="text-[9px] font-medium px-1.5 py-0.5 rounded border"
              style={{
                backgroundColor: "#0c0f14",
                borderColor: `${meta.color}55`,
                color: meta.color,
              }}
            >
              {meta.label}
            </span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});

function buildExplanation(
  relType: RelationType,
  evClass: EvidenceClass,
  data?: GraphEdgeData | null,
): string {
  const src = data?.source_symbol || data?.source_file || "This component";
  const tgt = data?.target_symbol || data?.target_file || "that component";

  const certaintyNote =
    evClass === "statically_verified"
      ? "This relationship was verified by static analysis."
      : evClass === "inferred"
      ? "This relationship is inferred — static analysis suggests it exists, but it has not been directly confirmed."
      : evClass === "unknown"
      ? "The nature of this relationship is unknown. It may not exist at runtime."
      : "";

  const map: Record<RelationType, string> = {
    imports: `${src} imports ${tgt}, making its exports available.`,
    calls: `${src} calls ${tgt} directly. ${certaintyNote}`,
    references: `${src} references ${tgt}. ${certaintyNote}`,
    contains: `${src} contains ${tgt} as a child component.`,
    implements: `${src} implements the contract defined by ${tgt}.`,
    inherits: `${src} inherits from ${tgt}.`,
    depends_on: `${src} depends on ${tgt}. Changes to ${tgt} may affect ${src}.`,
    invokes_api: `${src} invokes an API exposed by ${tgt}.`,
    reads_config: `${src} reads configuration from ${tgt}.`,
    writes_data: `${src} writes data that ${tgt} processes or stores.`,
    tested_by: `${tgt} contains tests that verify the behavior of ${src}.`,
    protected_by: `${src} is protected by a security control in ${tgt}.`,
    potentially_affected_by: `${src} may be affected by changes to ${tgt}. This is an inferred relationship.`,
  };

  return map[relType] ?? `${src} is related to ${tgt}. ${certaintyNote}`;
}
