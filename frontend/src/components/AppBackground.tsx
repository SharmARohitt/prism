"use client";

import { usePathname } from "next/navigation";
import GradientASCII from "./GradientASCII";

/**
 * AppBackground — very subtle full-screen GradientASCII for inner pages.
 * Hidden on "/" (landing manages its own visual panel).
 * Low opacity so content stays perfectly readable.
 */
export function AppBackground() {
  const pathname = usePathname();

  if (pathname === "/") return null;

  return (
    <div
      className="fixed inset-0 z-0 pointer-events-none"
      aria-hidden="true"
      style={{ opacity: 0.13 }}
    >
      <GradientASCII
        colors={["#060b12", "#0c1828", "#112236", "#172d48"]}
        shape="horizon"
        characters=" .:-"
        cellSize={22}
        density={0.45}
        glyphOpacity={0.5}
        glow={0}
        depthOfField={0}
        flicker={0.03}
        softness={0.85}
        scale={1.5}
        flow={0.2}
        speed={0.3}
        gradientOpacity={0.45}
        grain={0.03}
        variation={0}
        mouseInteraction={false}
        intro={false}
        lightMode={false}
      />
    </div>
  );
}
