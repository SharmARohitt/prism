"use client";

import GradientASCII from "./GradientASCII";

type HomeGradientProps = {
  className?: string;
};

/**
 * HomeGradient — PRISM visual panel background.
 *
 * Colour strategy: only very dark blues + dim teal. No near-white, no bright
 * cyan — those create the white-beam artefact. The "horizon" shape works like
 * a dark seascape: deep ocean at the bottom, slightly less dark sky above.
 *
 * Settings tuned to avoid the white bloom:
 *  - No colour above ~#1e4060 (dark steel blue)
 *  - gradientOpacity low (0.55) so the colour field doesn't overpower
 *  - glow=0 — glow passes through bright colours and amplifies them
 *  - softness high — diffuses any edge contrast
 *  - speed slow — atmospheric, not distracting
 */
export default function HomeGradient({ className }: HomeGradientProps) {
  return (
    <div
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
      }}
    >
      <GradientASCII
        /* All dark — deepest void → dark navy → dark steel blue.
           Never goes lighter than ~#1e4a6e so no white/bright beam. */
        colors={["#060b12", "#0b1624", "#0f2035", "#142944", "#1e4060"]}
        shape="horizon"
        characters=" .:=+xX0#"
        cellSize={16}
        density={0.65}
        glyphOpacity={0.55}
        glow={0}           /* glow=0 is essential — kills the bright bloom */
        depthOfField={0.05}
        flicker={0.08}
        softness={0.78}    /* very soft — diffuses any remaining edge contrast */
        scale={1.15}
        flow={0.4}
        speed={0.55}
        gradientOpacity={0.5}   /* low — keeps the gradient dark */
        grain={0.05}
        variation={0}
        mouseInteraction
        scrambleRadius={0.1}
        clickEffect="wave"
        intro
        lightMode={false}
      />
    </div>
  );
}
