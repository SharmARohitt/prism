"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck } from "lucide-react";

export function Navbar() {
  const pathname = usePathname();

  // No navbar on landing page — it has its own identity section
  if (pathname === "/") return null;

  // Derive the repo segment if we're inside /repos/[id]
  const repoMatch = pathname.match(/^\/repos\/([^/]+)/);
  const repoId = repoMatch?.[1];

  return (
    <nav
      className="sticky top-0 z-50"
      style={{
        borderBottom: "1px solid rgba(94,234,212,0.12)",
        background: "rgba(7,9,12,0.82)",
        backdropFilter: "blur(18px) saturate(1.5)",
        WebkitBackdropFilter: "blur(18px) saturate(1.5)",
      }}
    >
      {/* Mint accent line at very top */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 1,
          background: "linear-gradient(90deg, transparent 0%, rgba(94,234,212,0.5) 40%, rgba(56,189,248,0.5) 70%, transparent 100%)",
        }}
      />

      <div className="mx-auto flex h-13 max-w-7xl items-center justify-between px-4 py-2.5">
        {/* Brand */}
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="relative">
            <ShieldCheck
              className="h-5 w-5 transition-all duration-200 group-hover:scale-110"
              style={{ color: "#5eead4", filter: "drop-shadow(0 0 6px rgba(94,234,212,0.4))" }}
            />
          </div>
          <div className="flex flex-col leading-none">
            <span
              className="text-sm font-bold tracking-wider"
              style={{ color: "#e2e8f0", letterSpacing: "0.18em" }}
            >
              PRISM
            </span>
            <span
              className="text-[8px] tracking-widest"
              style={{ color: "#475569", letterSpacing: "0.22em" }}
            >
              REPO INTELLIGENCE
            </span>
          </div>
        </Link>

        {/* In-repo navigation */}
        {repoId && (
          <div className="flex items-center gap-0.5">
            <NavPill
              href={`/repos/${repoId}`}
              label="Dashboard"
              active={pathname === `/repos/${repoId}`}
            />
            <NavPill
              href={`/repos/${repoId}/timeline`}
              label="Timeline"
              active={pathname.includes("/timeline")}
            />
            <NavPill
              href={`/repos/${repoId}/settings`}
              label="Settings"
              active={pathname.includes("/settings")}
            />
          </div>
        )}

        {/* Right side */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-xs transition-colors"
            style={{ color: "#475569" }}
            onMouseEnter={e => (e.currentTarget.style.color = "#5eead4")}
            onMouseLeave={e => (e.currentTarget.style.color = "#475569")}
          >
            All repositories
          </Link>
        </div>
      </div>
    </nav>
  );
}

function NavPill({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className="px-3 py-1.5 rounded text-xs font-medium transition-all duration-150"
      style={{
        color: active ? "#5eead4" : "#64748b",
        background: active ? "rgba(94,234,212,0.08)" : "transparent",
        border: active ? "1px solid rgba(94,234,212,0.2)" : "1px solid transparent",
      }}
      onMouseEnter={e => {
        if (!active) {
          e.currentTarget.style.color = "#94a3b8";
          e.currentTarget.style.background = "rgba(255,255,255,0.04)";
        }
      }}
      onMouseLeave={e => {
        if (!active) {
          e.currentTarget.style.color = "#64748b";
          e.currentTarget.style.background = "transparent";
        }
      }}
    >
      {label}
    </Link>
  );
}
