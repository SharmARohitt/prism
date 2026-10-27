"use client";

import { useState, useRef, useCallback } from "react";
import { Search, X, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { NODE_TYPE_META, type SearchResult } from "@/lib/graphTypes";
import { cn } from "@/lib/utils";

interface GraphSearchProps {
  repoId: string;
  onSelect: (nodeId: string) => void;
}

export function GraphSearch({ repoId, onSelect }: GraphSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const search = useCallback(
    (q: string) => {
      if (q.trim().length < 2) {
        setResults([]);
        setOpen(false);
        return;
      }
      setLoading(true);
      api
        .searchGraph(repoId, q.trim(), 15)
        .then((r) => {
          setResults(r.results);
          setOpen(true);
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    },
    [repoId],
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(val), 250);
  };

  const handleSelect = (nodeId: string) => {
    onSelect(nodeId);
    setOpen(false);
    setQuery("");
    setResults([]);
  };

  const handleClear = () => {
    setQuery("");
    setResults([]);
    setOpen(false);
    inputRef.current?.focus();
  };

  return (
    <div className="relative">
      {/* Input */}
      <div
        className="flex items-center gap-2 rounded-md border px-3 py-1.5 transition-colors"
        style={{
          backgroundColor: "#0c0f14",
          borderColor: open ? "#2dd4bf55" : "#1a1f28",
          width: 240,
        }}
      >
        {loading ? (
          <Loader2 className="h-3.5 w-3.5 text-teal-500 animate-spin shrink-0" />
        ) : (
          <Search className="h-3.5 w-3.5 text-slate-500 shrink-0" />
        )}
        <input
          ref={inputRef}
          value={query}
          onChange={handleChange}
          onFocus={() => results.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search nodes…"
          className="bg-transparent text-xs text-slate-200 placeholder:text-slate-600 outline-none flex-1 min-w-0"
          aria-label="Search graph nodes"
        />
        {query && (
          <button onClick={handleClear} className="text-slate-600 hover:text-slate-400">
            <X className="h-3 w-3" />
          </button>
        )}
      </div>

      {/* Results dropdown */}
      {open && results.length > 0 && (
        <div
          className="absolute top-full mt-1 left-0 w-full z-50 rounded-md border shadow-xl overflow-hidden"
          style={{
            backgroundColor: "#0a0d12",
            borderColor: "#1a1f28",
            maxHeight: 280,
            overflowY: "auto",
          }}
        >
          {results.map((r) => {
            const meta = NODE_TYPE_META[r.type] ?? NODE_TYPE_META["file"];
            return (
              <button
                key={r.node_id}
                onMouseDown={() => handleSelect(r.node_id)}
                className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-white/5 transition-colors text-left"
              >
                <span
                  className="text-[10px] w-5 h-5 flex items-center justify-center rounded shrink-0"
                  style={{ backgroundColor: `${meta.color}20`, color: meta.color }}
                >
                  {meta.icon}
                </span>
                <div className="min-w-0">
                  <div className="text-xs text-slate-200 truncate">{r.label}</div>
                  {r.file_path && (
                    <div className="text-[10px] text-slate-500 font-mono truncate">
                      {r.file_path}
                    </div>
                  )}
                </div>
                <span
                  className="text-[9px] ml-auto shrink-0 px-1.5 py-0.5 rounded"
                  style={{ backgroundColor: `${meta.color}20`, color: meta.color }}
                >
                  {meta.label}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {open && query.length >= 2 && results.length === 0 && !loading && (
        <div
          className="absolute top-full mt-1 left-0 w-full z-50 rounded-md border px-3 py-2 text-xs text-slate-500"
          style={{ backgroundColor: "#0a0d12", borderColor: "#1a1f28" }}
        >
          No nodes found for "{query}"
        </div>
      )}
    </div>
  );
}
