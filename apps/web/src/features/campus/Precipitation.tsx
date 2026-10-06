'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import {
  BufferGeometry,
  Float32BufferAttribute,
  NormalBlending,
  type ShaderMaterial,
  Vector3,
} from 'three';

/** Particles live in a box that follows the camera target, in metres. */
const BOX: [number, number, number] = [440, 200, 440];

const STYLE = {
  rain: { count: 14000, speed: 26, length: 3.4 },
  snow: { count: 6000, speed: 1.6, length: 0 },
} as const;

const vertexShader = /* glsl */ `
  attribute vec3 aSeed;
  attribute float aEnd;
  uniform float uTime;
  uniform vec3 uCenter;
  uniform vec3 uBox;
  uniform float uSpeed;
  uniform float uLength;
  uniform float uSnow;
  varying float vEnd;
  void main() {
    vec3 p = aSeed * uBox;
    p.y = mod(p.y - uTime * uSpeed * (0.8 + aSeed.x * 0.4), uBox.y);
    // Snow sways; rain leans slightly with the wind.
    p.x += uSnow * sin(uTime * 0.7 + aSeed.z * 40.0) * 1.6 + (1.0 - uSnow) * (uBox.y - p.y) * 0.04;
    vec3 world = uCenter + p - vec3(uBox.x * 0.5, 0.0, uBox.z * 0.5);
    world.y -= aEnd * uLength;
    vEnd = aEnd;
    vec4 mv = viewMatrix * vec4(world, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSnow * clamp(260.0 / -mv.z, 1.0, 6.0);
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uSnow;
  varying float vEnd;
  void main() {
    if (uSnow > 0.5) {
      float d = length(gl_PointCoord - 0.5);
      if (d > 0.5) discard;
      gl_FragColor = vec4(1.0, 1.0, 1.0, 0.9 * (1.0 - smoothstep(0.25, 0.5, d)));
      return;
    }
    // Soft rain blue: reads on pale paving by day and against the night sky.
    gl_FragColor = vec4(0.36, 0.55, 0.9, 0.85 * (1.0 - vEnd * 0.7));
  }
`;

export function Precipitation({ kind }: { kind: 'rain' | 'snow' }) {
  const style = STYLE[kind];
  const snow = kind === 'snow';
  const controls = useThree((s) => s.controls) as {
    getTarget?: (out: Vector3) => Vector3;
  } | null;
  const material = useRef<ShaderMaterial>(null);
  const target = useMemo(() => new Vector3(), []);

  const geometry = useMemo(() => {
    const perDrop = snow ? 1 : 2;
    const seeds = new Float32Array(style.count * perDrop * 3);
    const ends = new Float32Array(style.count * perDrop);
    const positions = new Float32Array(style.count * perDrop * 3);
    // Deterministic hash so the pattern is stable between renders.
    const random = (n: number) => {
      const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
      return x - Math.floor(x);
    };
    for (let i = 0; i < style.count; i++) {
      const seed = [random(i * 3), random(i * 3 + 1), random(i * 3 + 2)];
      for (let k = 0; k < perDrop; k++) {
        const v = i * perDrop + k;
        seeds.set(seed, v * 3);
        ends[v] = k;
      }
    }
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(positions, 3));
    g.setAttribute('aSeed', new Float32BufferAttribute(seeds, 3));
    g.setAttribute('aEnd', new Float32BufferAttribute(ends, 1));
    return g;
  }, [snow, style.count]);
  useEffect(() => () => geometry.dispose(), [geometry]);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uCenter: { value: new Vector3() },
      uBox: { value: new Vector3(...BOX) },
      uSpeed: { value: style.speed },
      uLength: { value: style.length },
      uSnow: { value: snow ? 1 : 0 },
    }),
    [snow, style.speed, style.length],
  );

  useFrame(({ clock }) => {
    const m = material.current;
    if (!m) return;
    m.uniforms.uTime!.value = clock.elapsedTime;
    if (controls?.getTarget) {
      controls.getTarget(target);
      (m.uniforms.uCenter!.value as Vector3).set(target.x, 0, target.z);
    }
  });

  const shader = (
    <shaderMaterial
      ref={material}
      vertexShader={vertexShader}
      fragmentShader={fragmentShader}
      uniforms={uniforms}
      transparent
      depthWrite={false}
      blending={NormalBlending}
    />
  );
  return snow ? (
    <points geometry={geometry} frustumCulled={false}>
      {shader}
    </points>
  ) : (
    <lineSegments geometry={geometry} frustumCulled={false}>
      {shader}
    </lineSegments>
  );
}
