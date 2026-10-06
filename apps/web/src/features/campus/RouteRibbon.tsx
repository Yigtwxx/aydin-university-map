'use client';

import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { Color, type ShaderMaterial } from 'three';

import { layers, palette } from './constants';
import { lineLength, ribbonGeometry } from './ribbon';
import type { GraphNode } from './types';

const DRAW_S = 1.1;
const LIFT_M = 0.12;

/**
 * Width grows with camera distance, so the route stays readable zoomed out
 * (about 3.5 m up close, never thinner than ~6 px on screen).
 */
const vertexShader = /* glsl */ `
  attribute vec3 aCenter;
  attribute vec3 aOffset;
  uniform float uHalfWidth;
  uniform float uPixelScale;
  varying vec2 vUv;
  #include <fog_pars_vertex>
  void main() {
    vUv = uv;
    float dist = distance(cameraPosition, aCenter);
    float halfWidth = max(uHalfWidth, dist * uPixelScale);
    vec4 mvPosition = modelViewMatrix * vec4(aCenter + aOffset * halfWidth, 1.0);
    gl_Position = projectionMatrix * mvPosition;
    #include <fog_vertex>
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform float uDrawn;
  uniform vec3 uColor;
  uniform vec3 uEdge;
  uniform float uShadow;
  varying vec2 vUv;
  #include <fog_pars_fragment>
  void main() {
    if (vUv.x > uDrawn) discard;
    float d = abs(vUv.y - 0.5) * 2.0;
    if (uShadow > 0.5) {
      // Soft contact shadow that lifts the route off the paving.
      gl_FragColor = vec4(0.04, 0.07, 0.14, 0.22 * (1.0 - smoothstep(0.35, 1.0, d)));
      return;
    }
    float aa = fwidth(d) * 1.2;
    vec3 color = mix(uColor, uEdge, smoothstep(0.72 - aa, 0.72 + aa, d));
    // Chevrons flowing towards the destination (tip ahead, at the centre line).
    float phase = fract((vUv.x + d * 2.4 - uTime * 4.5) / 7.0);
    float chevron = smoothstep(0.0, 0.05, phase) * (1.0 - smoothstep(0.17, 0.22, phase));
    chevron *= 1.0 - smoothstep(0.5 - aa, 0.56 + aa, d);
    color = mix(color, uEdge, chevron * 0.5);
    gl_FragColor = vec4(color, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    #include <fog_fragment>
  }
`;

function makeUniforms(shadow: boolean) {
  return {
    uTime: { value: 0 },
    uDrawn: { value: 0 },
    uColor: { value: new Color(palette.route) },
    uEdge: { value: new Color(palette.routeEdge) },
    // The contact shadow is twice as wide as the line.
    uHalfWidth: { value: shadow ? 3.5 : 1.75 },
    uPixelScale: { value: shadow ? 0.0084 : 0.0042 },
    uShadow: { value: shadow ? 1 : 0 },
    fogColor: { value: new Color() },
    fogNear: { value: 1 },
    fogFar: { value: 2000 },
    fogDensity: { value: 0 },
  };
}

export function RouteRibbon({
  nodes,
  reducedMotion,
}: {
  nodes: GraphNode[];
  reducedMotion: boolean;
}) {
  const points = useMemo(
    () => nodes.map((n) => [n.enu[0], n.enu[1]] as [number, number]),
    [nodes],
  );
  const length = useMemo(() => lineLength(points), [points]);
  const geometry = useMemo(
    () => ribbonGeometry([{ points, width: 3.5 }], LIFT_M),
    [points],
  );
  const shadow = useMemo(
    () => ribbonGeometry([{ points, width: 7 }], LIFT_M * 0.5),
    [points],
  );
  useEffect(
    () => () => {
      geometry?.dispose();
      shadow?.dispose();
    },
    [geometry, shadow],
  );

  const uniforms = useMemo(() => makeUniforms(false), []);
  const shadowUniforms = useMemo(() => makeUniforms(true), []);
  const core = useRef<ShaderMaterial>(null);
  const under = useRef<ShaderMaterial>(null);
  const started = useRef<number | undefined>(undefined);
  useEffect(() => {
    started.current = undefined;
  }, [geometry]);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    started.current ??= t;
    const progress = reducedMotion
      ? 1
      : Math.min(1, (t - started.current) / DRAW_S);
    const drawn = (1 - (1 - progress) ** 3) * length + 0.01;
    for (const material of [core.current, under.current]) {
      if (!material) continue;
      material.uniforms.uTime!.value = reducedMotion ? 0 : t;
      material.uniforms.uDrawn!.value = drawn;
    }
  });

  if (!geometry || !shadow) return null;
  return (
    <>
      <mesh
        geometry={shadow}
        renderOrder={layers.routeShadow}
        frustumCulled={false}
      >
        <shaderMaterial
          vertexShader={vertexShader}
          fragmentShader={fragmentShader}
          ref={under}
          uniforms={shadowUniforms}
          transparent
          depthWrite={false}
          fog
        />
      </mesh>
      <mesh
        geometry={geometry}
        renderOrder={layers.route}
        frustumCulled={false}
      >
        <shaderMaterial
          vertexShader={vertexShader}
          fragmentShader={fragmentShader}
          ref={core}
          uniforms={uniforms}
          depthWrite={false}
          fog
        />
      </mesh>
    </>
  );
}
