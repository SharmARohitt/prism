"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Info } from "lucide-react";
import { NODE_TYPE_META, EDGE_TYPE_META, EVIDENCE_META } from "@/lib/graphTypes";

/**
 * Scrollable, always-accessible legend panel.
 * Sits in a fixed position in the graph's bottom-left corner.
 * Has its own scroll area so it never overflows the graph canvas.
 */
export function GraphLegend() {
  const [open, setOpen] = useState(true); // open by default

  return (
    <div
      className="rounded-lg border overflow-hidden flex flex-col"
      style={{
        backgroundColor: "#09090d",
        borderColor: "#1a1f28",
        maxHeight: open ? 360 : 36,
        width: 190,
        transition: "max-height 0.2s ease",
      }}
    >
      {/* Header — always visible, click to toggle */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center justify-between w-full px-3 py-2 text-xs text-slate-300 hover:text-white transition-colors shrink-0 border-b"
        style={{ borderColor: open ? "#1a1f28" : "transparent" }}
      >
        <span className="font-semibold flex items-center gap-1.5">
          <Info className="h-3 w-3 text-teal-400" />
          Legend
        </span>
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>

      {/* Scrollable content area */}
      {open && (
        <div
          className="px-3 py-2.5 space-y-2.5 overflow-y-auto no-scrollbar"
          style={{ scrollbarWidth: "thin" }}
        >
          {/* Node Types */}
          <div>
            <p className="text-[9px] uppercase tracking-wider text-slate-600 mb-1.5 font-semibold">
              Node Types
            </p>
            <div className="space-y-1">
              {(
                [
                  "module",
                  "file",
                  "class",
                  "function",
                  "method",
                  "endpoint",
                  "security_control",
                  "test",
                  "config",
                ] as const
              ).map((type) => {
                const m = NODE_TYPE_META[type];
                return (
                  <div key={type} className="flex items-center gap-2">
                    <span
                      className="text-[10px] w-4 h-4 flex items-center justify-center rounded shrink-0"
                      style={{ backgroundColor: `${m.color}20`, color: m.color }}
                    >
                      {m.icon}
                    </span>
                    <span className="text-[11px] text-slate-400">{m.label}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="border-t pt-2" style={{ borderColor: "#111418" }}>
            <p className="text-[9px] uppercase tracking-wider text-slate-600 mb-1.5 font-semibold">
              Relationship Types
            </p>
            <div className="space-y-1">
              {(
                [
                  "imports",
                  "calls",
                  "depends_on",
                  "tested_by",
                  "protected_by",
                  "potentially_affected_by",
                ] as const
              ).map((type) => {
                const m = EDGE_TYPE_META[type];
                return (
                  <div key={type} className="flex items-center gap-2">
                    <div
                      className="w-5 shrink-0"
                      style={{
                        borderTop: m.dashed
                          ? `1.5px dashed ${m.color}`
                          : `1.5px solid ${m.color}`,
                      }}
                    />
                    <span className="text-[11px] text-slate-400">{m.label}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="border-t pt-2" style={{ borderColor: "#111418" }}>
            <p className="text-[9px] uppercase tracking-wider text-slate-600 mb-1.5 font-semibold">
              Evidence Quality
            </p>
            <div className="space-y-1">
              {(
                Object.entries(EVIDENCE_META) as [
                  string,
                  { label: string; color: string },
                ][]
              ).map(([key, m]) => (
                <div key={key} className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: m.color }}
                  />
                  <span className="text-[11px] text-slate-400">{m.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="border-t pt-2" style={{ borderColor: "#111418" }}>
            <p className="text-[9px] uppercase tracking-wider text-slate-600 mb-1.5 font-semibold">
              Indicators
            </p>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
                <span className="text-[11px] text-slate-400">Security-sensitive</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-amber-400 shrink-0" />
                <span className="text-[11px] text-slate-400">Recently changed</span>
              </div>
              <div className="flex items-center gap-2">
                <div
                  className="w-3 h-3 rounded shrink-0 border border-dashed"
                  style={{ borderColor: "#475569", backgroundColor: "#0c0f14" }}
                />
                <span className="text-[11px] text-slate-400">Possibly dead code</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
