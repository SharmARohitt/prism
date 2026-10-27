"use client";

import { useEffect, useRef } from "react";

/**
 * PrismDiagram — the visual centerpiece of the PRISM landing page.
 *
 * Renders a 3D optical prism that splits an incoming "white light" beam
 * (representing raw repository data) into coloured bands, each labeled
 * with a layer of PRISM's intelligence stack.
 *
 * Fully canvas-based, single render loop, zero dependencies beyond React.
 * Respects prefers-reduced-motion. Pauses when tab is hidden.
 */
export default function PrismDiagram() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let t = 0;
    let visible = true;
    let disposed = false;

    const BANDS = [
      { color: "#5eead4", label: "Symbols & Relationships", alpha: 0.9 },
      { color: "#38bdf8", label: "Import & Call Graph",     alpha: 0.85 },
      { color: "#818cf8", label: "Security Analysis",       alpha: 0.85 },
      { color: "#c084fc", label: "PR Evidence Layer",       alpha: 0.8 },
      { color: "#f472b6", label: "LLM Explanation",         alpha: 0.75 },
    ];

    function draw(now: number) {
      raf = 0;
      if (disposed || !visible || document.hidden) return;
      if (!canvas || !ctx) return;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const W = canvas.offsetWidth;
      const H = canvas.offsetHeight;
      if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
        canvas.width = Math.round(W * dpr);
        canvas.height = Math.round(H * dpr);
        ctx.scale(dpr, dpr);
      }
      ctx.clearRect(0, 0, W, H);

      if (!prefersReduced) t = now * 0.0004;

      const cx = W * 0.5;
      const cy = H * 0.52;

      // ── Prism geometry ──────────────────────────────────────
      // Equilateral triangle, tip pointing up-right
      const prismH = Math.min(W, H) * 0.44;
      const prismW = prismH * 1.15;
      const prismCx = cx + W * 0.04;
      const prismCy = cy + prismH * 0.06;

      // Triangle vertices: top-right, bottom-left, bottom-right
      const vTop   = { x: prismCx + prismW * 0.28, y: prismCy - prismH * 0.5 };
      const vBotL  = { x: prismCx - prismW * 0.5,  y: prismCy + prismH * 0.5 };
      const vBotR  = { x: prismCx + prismW * 0.5,  y: prismCy + prismH * 0.5 };

      // ── Incoming beam ────────────────────────────────────────
      // Single white beam entering the left face, with a soft pulse
      const pulse = prefersReduced ? 0 : Math.sin(t * 2.1) * 0.04;
      const beamY = prismCy - prismH * (0.12 + pulse);
      const beamEntryX = vBotL.x + (vTop.x - vBotL.x) * 0.42;
      const beamEntryY = vBotL.y + (vTop.y - vBotL.y) * 0.42;

      // Beam from left edge → left face
      const beamStartX = W * 0.045;
      const beamStartY = beamY + H * 0.005;

      // Draw incoming beam (white ray)
      const beamGrad = ctx.createLinearGradient(beamStartX, beamStartY, beamEntryX, beamEntryY);
      beamGrad.addColorStop(0, "rgba(200,220,230,0)");
      beamGrad.addColorStop(0.5, "rgba(200,220,230,0.18)");
      beamGrad.addColorStop(1, "rgba(220,240,250,0.45)");

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(beamStartX, beamStartY - 2.5);
      ctx.lineTo(beamEntryX, beamEntryY - 1);
      ctx.lineTo(beamEntryX, beamEntryY + 1);
      ctx.lineTo(beamStartX, beamStartY + 2.5);
      ctx.closePath();
      ctx.fillStyle = beamGrad;
      ctx.fill();
      ctx.restore();

      // "REPOSITORY DATA" label on incoming beam
      ctx.save();
      ctx.font = "500 9px 'JetBrains Mono', ui-monospace, monospace";
      ctx.letterSpacing = "0.1em";
      ctx.fillStyle = "rgba(180,205,215,0.55)";
      ctx.textAlign = "left";
      ctx.fillText("REPOSITORY DATA", beamStartX + 2, beamStartY - 9);
      ctx.restore();

      // ── Prism fill ───────────────────────────────────────────
      // Subtle dark glass with inner glow
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(vTop.x, vTop.y);
      ctx.lineTo(vBotL.x, vBotL.y);
      ctx.lineTo(vBotR.x, vBotR.y);
      ctx.closePath();

      // Glass fill
      const glassFill = ctx.createLinearGradient(vBotL.x, vBotL.y, vTop.x, vTop.y);
      glassFill.addColorStop(0, "rgba(8, 20, 36, 0.85)");
      glassFill.addColorStop(0.5, "rgba(14, 32, 58, 0.72)");
      glassFill.addColorStop(1, "rgba(20, 48, 78, 0.55)");
      ctx.fillStyle = glassFill;
      ctx.fill();
      ctx.restore();

      // Inner glow (refraction simulation)
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(vTop.x, vTop.y);
      ctx.lineTo(vBotL.x, vBotL.y);
      ctx.lineTo(vBotR.x, vBotR.y);
      ctx.closePath();
      const innerGlow = ctx.createRadialGradient(
        prismCx - prismW * 0.05, prismCy - prismH * 0.05, 0,
        prismCx - prismW * 0.05, prismCy - prismH * 0.05, prismW * 0.5
      );
      const glowPulse = prefersReduced ? 0 : Math.sin(t * 1.6) * 0.04;
      innerGlow.addColorStop(0, `rgba(56, 189, 248, ${0.08 + glowPulse})`);
      innerGlow.addColorStop(0.5, `rgba(94, 234, 212, ${0.04 + glowPulse * 0.5})`);
      innerGlow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = innerGlow;
      ctx.fill();
      ctx.restore();

      // Prism edges
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(vTop.x, vTop.y);
      ctx.lineTo(vBotL.x, vBotL.y);
      ctx.lineTo(vBotR.x, vBotR.y);
      ctx.closePath();
      ctx.strokeStyle = "rgba(94, 140, 160, 0.45)";
      ctx.lineWidth = 1;
      ctx.stroke();

      // Highlight on top edge
      ctx.beginPath();
      ctx.moveTo(vTop.x, vTop.y);
      ctx.lineTo(vBotR.x, vBotR.y);
      ctx.strokeStyle = "rgba(180, 230, 240, 0.22)";
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();

      // ── Refracted bands (right face) ─────────────────────────
      // Fan of coloured rays exiting the right face, spreading downward
      const exitX = vBotR.x;

      // Band fan spread: top band exits near vTop-vBotR midpoint, bottom near vBotR
      const bandCount = BANDS.length;
      const fanTopY  = vTop.y   + (vBotR.y - vTop.y) * 0.22;
      const fanBotY  = vBotR.y  - (vBotR.y - vTop.y) * 0.06;
      const fanSpan  = fanBotY - fanTopY;

      // Endpoint for each band (right side of canvas, spreading out)
      const endX = W * 0.97;
      const endTopY = cy - prismH * 0.68;
      const endBotY = cy + prismH * 0.72;
      const endSpan = endBotY - endTopY;

      BANDS.forEach((band, i) => {
        const k = i / (bandCount - 1);
        const exitY = fanTopY + fanSpan * k;
        const endY  = endTopY + endSpan * k;
        const widthAtExit = 1.8 + i * 0.4;
        const widthAtEnd  = 3.5 + i * 1.2;

        // Animated flicker
        const flicker = prefersReduced ? 0 : Math.sin(t * 1.8 + i * 0.9) * 0.07;

        // Draw band as a filled quad
        ctx.save();
        const bandGrad = ctx.createLinearGradient(exitX, exitY, endX, endY);
        bandGrad.addColorStop(0, hexWithAlpha(band.color, 0.0));
        bandGrad.addColorStop(0.12, hexWithAlpha(band.color, (0.55 + flicker) * band.alpha));
        bandGrad.addColorStop(0.6, hexWithAlpha(band.color, (0.38 + flicker * 0.5) * band.alpha));
        bandGrad.addColorStop(1, hexWithAlpha(band.color, 0.0));
        ctx.fillStyle = bandGrad;

        ctx.beginPath();
        ctx.moveTo(exitX, exitY - widthAtExit);
        ctx.lineTo(endX, endY - widthAtEnd);
        ctx.lineTo(endX, endY + widthAtEnd);
        ctx.lineTo(exitX, exitY + widthAtExit);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // Band label
        const labelX = exitX + (endX - exitX) * 0.38;
        const labelY = endY + widthAtEnd * 0.5 - 2;

        ctx.save();
        ctx.font = "500 9.5px 'JetBrains Mono', ui-monospace, monospace";
        ctx.letterSpacing = "0.08em";
        ctx.fillStyle = hexWithAlpha(band.color, 0.72);
        ctx.textAlign = "left";
        ctx.fillText(band.label, labelX + 6, labelY + 14);

        // Small dot at end of band
        ctx.beginPath();
        ctx.arc(endX - 8, endY, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = hexWithAlpha(band.color, 0.6 + flicker);
        ctx.fill();
        // Glow
        const dotGlow = ctx.createRadialGradient(endX - 8, endY, 0, endX - 8, endY, 14);
        dotGlow.addColorStop(0, hexWithAlpha(band.color, 0.2 + flicker * 0.3));
        dotGlow.addColorStop(1, hexWithAlpha(band.color, 0));
        ctx.fillStyle = dotGlow;
        ctx.beginPath();
        ctx.arc(endX - 8, endY, 14, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      });

      // ── Prism label ──────────────────────────────────────────
      ctx.save();
      ctx.font = "600 9px 'JetBrains Mono', ui-monospace, monospace";
      ctx.letterSpacing = "0.18em";
      ctx.fillStyle = "rgba(160,190,200,0.5)";
      ctx.textAlign = "center";
      ctx.fillText("PRISM", prismCx - prismW * 0.06, prismCy + prismH * 0.14);
      ctx.restore();

      // ── Corner decorations ───────────────────────────────────
      drawCorner(ctx, 12, 12, 14, "tr");
      drawCorner(ctx, W - 12, H - 12, 14, "bl");

      // Field index
      ctx.save();
      ctx.font = "500 8px 'JetBrains Mono', ui-monospace, monospace";
      ctx.letterSpacing = "0.14em";
      ctx.fillStyle = "rgba(140,170,180,0.38)";
      ctx.textAlign = "left";
      ctx.fillText("FIELD / 001", 20, 22);
      ctx.textAlign = "right";
      ctx.fillText("SIGNAL IN THE SOURCE", W - 20, H - 18);
      ctx.restore();

      if (!prefersReduced || t === 0) {
        raf = requestAnimationFrame(draw);
      }
    }

    const visibilityHandler = () => {
      visible = !document.hidden;
      if (visible && !raf && !disposed) raf = requestAnimationFrame(draw);
    };

    const intersectionObs = new IntersectionObserver((entries) => {
      visible = entries.some(e => e.isIntersecting);
      if (visible && !raf && !disposed) raf = requestAnimationFrame(draw);
    });
    intersectionObs.observe(canvas);
    document.addEventListener("visibilitychange", visibilityHandler);
    raf = requestAnimationFrame(draw);

    return () => {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      intersectionObs.disconnect();
      document.removeEventListener("visibilitychange", visibilityHandler);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        display: "block",
      }}
    />
  );
}

// ── Helpers ────────────────────────────────────────────────

function hexWithAlpha(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
}

function drawCorner(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  corner: "tl" | "tr" | "bl" | "br",
) {
  const dx = corner.includes("r") ? 1 : -1;
  const dy = corner.includes("b") ? 1 : -1;
  ctx.save();
  ctx.strokeStyle = "rgba(94,160,175,0.38)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x + dx * size, y);
  ctx.lineTo(x, y);
  ctx.lineTo(x, y + dy * size);
  ctx.stroke();
  ctx.restore();
}
