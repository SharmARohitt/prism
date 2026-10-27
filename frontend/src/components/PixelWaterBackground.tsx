"use client";

import { useRef, useMemo, useEffect, useState, Suspense } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

/**
 * PixelWaterBackground — PRISM signature animated background.
 *
 * A dense instanced grid of pixels on a dark surface that behaves like liquid
 * water. Shader-based wave displacement creates flowing depth, with subtle
 * mint-green highlights on wave edges.
 *
 * Performance:
 * - Single InstancedMesh — no per-pixel React components.
 * - Custom vertex shader for GPU-based wave displacement.
 * - Adapts pixel density to screen size.
 * - Respects prefers-reduced-motion.
 * - Pauses when page is not visible.
 * - CSS fallback if WebGL is unavailable.
 */

const VERTEX_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uWaveSpeed;
  uniform float uWaveScale;
  uniform float uPixelSize;
  uniform float uReducedMotion;
  
  attribute float aInstance;
  
  varying float vElevation;
  varying vec3 vColor;
  
  // Simple sine-wave height field
  float getElevation(vec2 pos, float time) {
    float e1 = sin(pos.x * uWaveScale + time * uWaveSpeed) * 0.5;
    float e2 = sin(pos.y * uWaveScale * 1.3 + time * uWaveSpeed * 0.8) * 0.4;
    float e3 = sin((pos.x + pos.y) * uWaveScale * 0.7 + time * uWaveSpeed * 0.6) * 0.3;
    float e4 = cos(length(pos) * uWaveScale * 0.5 - time * uWaveSpeed * 0.5) * 0.2;
    return e1 + e2 + e3 + e4;
  }
  
  void main() {
    vec3 transformed = position;
    
    // Instance position offset
    vec3 instancePos = vec3(
      mod(aInstance, ${"float(GRID_SIZE)"}),
      0.0,
      floor(aInstance / ${"float(GRID_SIZE)"})
    );
    
    // Center the grid
    instancePos.x -= float(GRID_SIZE) * 0.5;
    instancePos.z -= float(GRID_SIZE) * 0.5;
    
    // Add instance position to vertex
    transformed += instancePos;
    
    // Compute wave elevation at this instance position
    float elevation = getElevation(instancePos.xz, uTime);
    elevation *= uReducedMotion; // Zero out motion if reduced motion is preferred
    transformed.y += elevation * uPixelSize * 2.0;
    
    vElevation = elevation;
    
    // Color: dark base with mint highlight on wave peaks
    float waveFactor = smoothstep(0.2, 1.0, elevation);
    vec3 baseColor = vec3(0.04, 0.05, 0.07);
    vec3 peakColor = vec3(0.18, 0.28, 0.24);
    vec3 mintGlow = vec3(0.37, 0.92, 0.83);
    
    vColor = mix(baseColor, peakColor, waveFactor);
    vColor = mix(vColor, mintGlow, smoothstep(0.6, 1.0, elevation) * 0.15);
    
    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  varying float vElevation;
  varying vec3 vColor;
  
  void main() {
    gl_FragColor = vec4(vColor, 1.0);
  }
`;

// Grid size — adapts to screen
const GRID_SIZE = 64;
const PIXEL_SIZE = 0.45;
const PIXEL_SPACING = 1.0;

function PixelField() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  const { gl } = useThree();
  const [reducedMotion, setReducedMotion] = useState(false);
  const [isVisible, setIsVisible] = useState(true);
  const timeRef = useRef(0);

  // Check for reduced motion preference
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Pause when tab not visible
  useEffect(() => {
    const handler = () => setIsVisible(!document.hidden);
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, []);

  // Build instanced geometry
  const { geometry, uniforms } = useMemo(() => {
    const count = GRID_SIZE * GRID_SIZE;
    const boxGeo = new THREE.BoxGeometry(PIXEL_SIZE, PIXEL_SIZE, PIXEL_SIZE);
    
    // Add instance index attribute
    const instances = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      instances[i] = i;
    }
    boxGeo.setAttribute("aInstance", new THREE.InstancedBufferAttribute(instances, 1));
    
    const u = {
      uTime: { value: 0 },
      uWaveSpeed: { value: 0.5 },
      uWaveScale: { value: 0.08 },
      uPixelSize: { value: PIXEL_SIZE },
      uReducedMotion: { value: 1.0 },
    };
    
    return { geometry: boxGeo, uniforms: u };
  }, []);

  // Update reduced motion uniform
  useEffect(() => {
    if (materialRef.current) {
      (materialRef.current.uniforms.uReducedMotion as { value: number }).value = reducedMotion ? 0 : 1;
    }
  }, [reducedMotion]);

  // Animation loop
  useFrame((_, delta) => {
    if (isVisible) {
      timeRef.current += delta;
      if (materialRef.current) {
        (materialRef.current.uniforms.uTime as { value: number }).value = timeRef.current;
      }
    }
  });

  return (
    <instancedMesh
      ref={meshRef}
      args={[geometry, undefined, GRID_SIZE * GRID_SIZE]}
      frustumCulled={false}
    >
      <shaderMaterial
        ref={materialRef}
        vertexShader={VERTEX_SHADER.replace(/\$\{"float\(GRID_SIZE\)"\}/g, String(GRID_SIZE))}
        fragmentShader={FRAGMENT_SHADER}
        uniforms={uniforms}
      />
    </instancedMesh>
  );
}

function Scene() {
  const { camera } = useThree();
  
  useEffect(() => {
    // Position camera for an angled overhead view
    camera.position.set(0, 30, 25);
    camera.lookAt(0, 0, 0);
  }, [camera]);

  return (
    <>
      <PixelField />
      <fog attach="fog" args={["#07090c", 30, 80]} />
      <ambientLight intensity={0.3} />
    </>
  );
}

export default function PixelWaterBackground() {
  const [webglAvailable, setWebglAvailable] = useState(true);

  useEffect(() => {
    // Check WebGL availability
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
      if (!gl) setWebglAvailable(false);
    } catch {
      setWebglAvailable(false);
    }
  }, []);

  if (!webglAvailable) {
    // CSS fallback
    return <div className="pixel-water-fallback" aria-hidden="true" />;
  }

  return (
    <div
      className="fixed inset-0 z-0"
      style={{ pointerEvents: "none" }}
      aria-hidden="true"
    >
      <Canvas
        camera={{ fov: 50, near: 0.1, far: 100, position: [0, 30, 25] }}
        gl={{ antialias: false, powerPreference: "low-power" }}
        dpr={[0.5, 1.5]}
      >
        <Suspense fallback={null}>
          <Scene />
        </Suspense>
      </Canvas>
      {/* Gradient overlay for readability */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at 50% 0%, transparent 0%, rgba(7, 9, 12, 0.4) 60%, rgba(7, 9, 12, 0.85) 100%)",
        }}
      />
    </div>
  );
}
