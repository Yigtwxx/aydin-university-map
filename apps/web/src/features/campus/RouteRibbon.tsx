'use client';

import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { Color, GreaterDepth, type ShaderMaterial } from 'three';

import { layers, palette } from './constants';
import { lineLength, ribbonGeometry } from './ribbon';
import { routePolyline, smoothRoute } from './routeLine';
import type { CampusGraph, GraphNode } from './types';

const DRAW_S = 1.2;
/** Above every flat ground layer (they sit at 0.05 m with polygon offset). */
const LIFT_M = 0.3;
const WIDTH_M = 3.2;

type XY = [number, number];

/** Extend both ends by ``by`` metres so the shader can round the caps. */
function extendEnds(points: XY[], by: number): XY[] {
  if (points.length < 2) return points;
  const ext = (a: XY, b: XY): XY => {
    const dx = a[0] - b[0];
    const dy = a[1] - b[1];
    const len = Math.hypot(dx, dy) || 1;
    return [a[0] + (dx / len) * by, a[1] + (dy / len) * by];
  };
  const n = points.length;
  return [
    ext(points[0]!, points[1]!),
    ...points,
    ext(points[n - 1]!, points[n - 2]!),
  ];
}

/**
 * Width grows with camera distance so the route stays readable zoomed out
 * (about 3.2 m up close, never thinner than ~7 px on screen).
 */
const vertexShader = /* glsl */ `
  attribute vec3 aCenter;
  attribute vec3 aOffset;
  uniform float uHalfWidth;
  uniform float uPixelScale;
  varying vec2 vUv;
  varying float vHalfWidth;
  #include <fog_pars_vertex>
  void main() {
    vUv = uv;
    float dist = distance(cameraPosition, aCenter);
    float halfWidth = max(uHalfWidth, dist * uPixelScale);
    vHalfWidth = halfWidth;
    vec4 mvPosition = modelViewMatrix * vec4(aCenter + aOffset * halfWidth, 1.0);
    gl_Position = projectionMatrix * mvPosition;
    #include <fog_vertex>
  }
`;

/**
 * Signed distance across the line (0 centre, 1 edge) with round caps, then:
 * a white casing, a blue core with a lighter spine, and a soft light pulse
 * that travels to the destination. ``uMode`` 1 draws the contact shadow,
 * 2 the faint dashed line seen through buildings.
 */
const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform float uDrawn;
  uniform float uLength;
  uniform float uCap;
  uniform vec3 uColor;
  uniform vec3 uSpine;
  uniform vec3 uEdge;
  uniform float uMode;
  uniform float uOpacity;
  varying vec2 vUv;
  varying float vHalfWidth;
  #include <fog_pars_fragment>
  void main() {
    float along = vUv.x - uCap;
    if (along > uDrawn) discard;
    float across = abs(vUv.y - 0.5) * 2.0;
    // Round caps: past either end, distance is to the end point.
    float over = max(-along, along - uLength) / vHalfWidth;
    float d = over > 0.0 ? length(vec2(over, across)) : across;
    float aa = max(fwidth(d), 1e-4) * 1.25;
    float inside = 1.0 - smoothstep(1.0 - aa, 1.0, d);
    if (inside <= 0.0) discard;

    if (uMode > 0.5 && uMode < 1.5) {
      // Soft contact shadow lifting the route off the paving.
      gl_FragColor = vec4(0.04, 0.07, 0.14, 0.26 * (1.0 - smoothstep(0.2, 1.0, d)));
      return;
    }
    if (uMode > 1.5) {
      // Hidden behind a building: thin dashes in the route colour.
      float dash = step(0.45, fract(along / 4.0));
      float core = 1.0 - smoothstep(0.5 - aa, 0.5 + aa, d);
      gl_FragColor = vec4(uColor, core * dash * uOpacity);
      #include <colorspace_fragment>
      return;
    }

    float casing = smoothstep(0.7 - aa, 0.7 + aa, d);
    float spine = 1.0 - smoothstep(0.0, 0.42, d);
    vec3 color = mix(uColor, uSpine, spine * 0.35);
    // A pulse of light every 34 m, moving at walking-pace times eight.
    float pulse = fract((along - uTime * 11.0) / 34.0);
    float glow = smoothstep(0.0, 0.12, pulse) * (1.0 - smoothstep(0.12, 0.3, pulse));
    color = mix(color, uSpine, glow * 0.65 * (1.0 - casing));
    color = mix(color, uEdge, casing);
    gl_FragColor = vec4(color, inside);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    #include <fog_fragment>
  }
`;

function makeUniforms(mode: 0 | 1 | 2, length: number) {
  const shadow = mode === 1;
  return {
    uTime: { value: 0 },
    uDrawn: { value: 0 },
    uLength: { value: length },
    uCap: { value: WIDTH_M },
    uColor: { value: new Color(palette.route) },
    uSpine: { value: new Color('#7FB3FF') },
    uEdge: { value: new Color(palette.routeEdge) },
    uMode: { value: mode },
    uOpacity: { value: 0.55 },
    // The contact shadow is twice as wide as the line.
    uHalfWidth: { value: shadow ? WIDTH_M : WIDTH_M / 2 },
    uPixelScale: { value: shadow ? 0.0096 : 0.0048 },
    fogColor: { value: new Color() },
    fogNear: { value: 1 },
    fogFar: { value: 2000 },
    fogDensity: { value: 0 },
  };
}

export function RouteRibbon({
  graph,
  nodes,
  reducedMotion,
  onTop = false,
}: {
  graph: CampusGraph;
  nodes: GraphNode[];
  reducedMotion: boolean;
  /** Draw over everything (photoreal tiles have their own uneven ground). */
  onTop?: boolean;
}) {
  const points = useMemo(
    () => smoothRoute(routePolyline(nodes, graph.edgeById)),
    [graph, nodes],
  );
  const length = useMemo(() => lineLength(points), [points]);
  // The extra length past each end becomes the round cap.
  const extended = useMemo(() => extendEnds(points, WIDTH_M), [points]);
  const geometry = useMemo(
    () => ribbonGeometry([{ points: extended, width: WIDTH_M }], LIFT_M),
    [extended],
  );
  const shadow = useMemo(
    () =>
      ribbonGeometry([{ points: extended, width: WIDTH_M * 2 }], LIFT_M * 0.6),
    [extended],
  );
  useEffect(
    () => () => {
      geometry?.dispose();
      shadow?.dispose();
    },
    [geometry, shadow],
  );

  const uniforms = useMemo(() => makeUniforms(0, length), [length]);
  const shadowUniforms = useMemo(() => makeUniforms(1, length), [length]);
  const hiddenUniforms = useMemo(() => makeUniforms(2, length), [length]);
  const materials = useRef<(ShaderMaterial | null)[]>([]);
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
    // Ease out, and let the cap past the destination draw in too.
    const drawn = (1 - (1 - progress) ** 3) * (length + WIDTH_M) + 0.01;
    for (const material of materials.current) {
      if (!material) continue;
      material.uniforms.uTime!.value = reducedMotion ? 0 : t;
      material.uniforms.uDrawn!.value = drawn;
    }
  });

  if (!geometry || !shadow) return null;
  const shared = {
    vertexShader,
    fragmentShader,
    transparent: true,
    depthWrite: false,
    // Beat the ground overlays' own offset so the route is never covered.
    polygonOffset: true,
    polygonOffsetFactor: -4,
    polygonOffsetUnits: -4,
    depthTest: !onTop,
  } as const;
  return (
    <>
      <mesh
        geometry={shadow}
        renderOrder={layers.routeShadow}
        frustumCulled={false}
      >
        <shaderMaterial
          {...shared}
          ref={(m) => {
            materials.current[0] = m;
          }}
          uniforms={shadowUniforms}
          fog
        />
      </mesh>
      <mesh
        geometry={geometry}
        renderOrder={layers.route}
        frustumCulled={false}
      >
        <shaderMaterial
          {...shared}
          ref={(m) => {
            materials.current[1] = m;
          }}
          uniforms={uniforms}
          fog
        />
      </mesh>
      {/* Where a building hides the route, show it through as faint dashes. */}
      {!onTop && (
        <mesh
          geometry={geometry}
          renderOrder={layers.route + 1}
          frustumCulled={false}
        >
          <shaderMaterial
            {...shared}
            depthFunc={GreaterDepth}
            ref={(m) => {
              materials.current[2] = m;
            }}
            uniforms={hiddenUniforms}
            fog
          />
        </mesh>
      )}
    </>
  );
}
