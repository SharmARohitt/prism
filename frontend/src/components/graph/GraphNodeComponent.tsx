"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { NODE_TYPE_META, type ArchGraphNode } from "@/lib/graphTypes";
import { cn } from "@/lib/utils";

export type GraphNodeData = ArchGraphNode & {
  selected?: boolean;
  dimmed?: boolean;
  changed?: boolean;
  is_possibly_dead?: boolean;
};

/**
 * Custom React Flow node with:
 * - Type icon + color accent
 * - Symbol count badge for modules/files
 * - Security-sensitive indicator
 * - Change indicator dot
 * - Evidence classification indicator
 * - Dimming when another node is focused
 */
export const GraphNodeComponent = memo(function GraphNodeComponent({
  data,
  selected,
}: NodeProps<GraphNodeData>) {
  const meta = NODE_TYPE_META[data.type] ?? NODE_TYPE_META["file"];
  const isSecSensitive = data.is_security_sensitive;
  const isDimmed = data.dimmed && !selected;
  const isChanged = data.changed;
  const isDead = data.is_possibly_dead;

  return (
    <div
      className={cn(
        "relative flex flex-col items-start px-2.5 py-1.5 rounded-md border transition-all duration-150 select-none",
        "min-w-[80px] max-w-[180px]",
        // Border changes with state
        selected
          ? "border-2 shadow-lg shadow-black/50"
          : isDimmed
          ? "border opacity-25"
          : "border hover:border-opacity-80",
      )}
      style={{
        borderColor: selected
          ? meta.color
          : isDead
          ? "#475569"
          : isDimmed
          ? "#1a1f28"
          : `${meta.color}55`,
        backgroundColor: selected ? `${meta.color}18` : "#0c0f14",
        borderStyle: isDead ? "dashed" : "solid",
        boxShadow: selected ? `0 0 0 1px ${meta.color}44, 0 4px 16px rgba(0,0,0,0.6)` : undefined,
        opacity: isDead && !selected ? 0.5 : 1,
      }}
    >
      {/* Handles */}
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: meta.color, width: 6, height: 6, border: "none" }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: meta.color, width: 6, height: 6, border: "none" }}
      />

      {/* Top row: icon + label */}
      <div className="flex items-center gap-1.5 w-full">
        {/* Type icon */}
        <span
          className="text-[10px] font-bold shrink-0 w-4 h-4 flex items-center justify-center rounded"
          style={{
            color: meta.color,
            backgroundColor: `${meta.color}22`,
          }}
        >
          {meta.icon}
        </span>

        {/* Label */}
        <span
          className="text-xs font-medium leading-tight truncate"
          style={{ color: selected ? meta.color : "#e2e8f0" }}
          title={data.label}
        >
          {data.label}
        </span>
      </div>

      {/* Bottom row: type + counts */}
      <div className="flex items-center gap-1.5 mt-0.5 w-full">
        <span className="text-[9px] font-medium" style={{ color: `${meta.color}aa` }}>
          {meta.label}
        </span>

        {/* Symbol count for modules/files */}
        {(data.type === "module" || data.type === "file") && data.symbol_count > 0 && (
          <span className="text-[9px] text-slate-500">
            {data.symbol_count} sym
          </span>
        )}

        {/* Incoming/outgoing */}
        {(data.incoming_count > 0 || data.outgoing_count > 0) && (
          <span className="text-[9px] text-slate-600 ml-auto">
            ↓{data.incoming_count} ↑{data.outgoing_count}
          </span>
        )}
      </div>

      {/* Security indicator */}
      {isSecSensitive && (
        <div
          className="absolute -top-1 -right-1 w-3 h-3 rounded-full flex items-center justify-center"
          style={{ backgroundColor: "#fb7185", fontSize: 7, color: "#fff" }}
          title="Security-sensitive component"
        >
          !
        </div>
      )}

      {/* Changed indicator */}
      {isChanged && (
        <div
          className="absolute -top-1 -left-1 w-2.5 h-2.5 rounded-full"
          style={{ backgroundColor: "#fbbf24" }}
          title="Recently changed"
        />
      )}
    </div>
  );
});
