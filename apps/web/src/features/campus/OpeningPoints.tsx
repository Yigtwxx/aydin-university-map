'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AdditiveBlending,
  BufferGeometry,
  Float32BufferAttribute,
  type PerspectiveCamera,
  type ShaderMaterial,
  Vector2,
} from 'three';

import {
  INTRO,
  INTRO_OVER,
  introClock,
  introLight,
  sampleIntroPoints,
} from './opening';
import { seedOf } from './massing';
import type { Building, CampusGraph, Ground } from './types';

/** Points of the opening: fewer on small screens. */
const BUDGET = { desktop: 120_000, phone: 60_000 };
/** Fast-forward once the visitor touches, scrolls or presses a key. */
const SKIP_SPEED = 4;
/** Frames to wait before the clock runs: shaders compile in the first ones. */
const WARMUP_FRAMES = 3;

/** Development only: `?openingAt=1.4` holds the opening at 1.4 s for review. */
function heldAt(): number | undefined {
  if (process.env.NODE_ENV === 'production') return undefined;
  const value = new URLSearchParams(window.location.search).get('openingAt');
  return value === null ? undefined : Number(value);
}

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uPixels;
  attribute vec3 aStart;
  attribute vec4 aTiming;
  attribute vec3 aColor;
  varying vec3 vColor;
  varying float vAlpha;

  float easeOutBack(float x) {
    float c1 = 1.25;
    float c3 = c1 + 1.0;
    return 1.0 + c3 * pow(x - 1.0, 3.0) + c1 * pow(x - 1.0, 2.0);
  }

  void main() {
    int kind = int(aTiming.z + 0.5);
    float seed = aTiming.w;
    float lift = clamp((uTime - aTiming.x) / ${INTRO.pointRiseS.toFixed(2)}, 0.0, 1.0);
    vec3 p = mix(aStart, position, easeOutBack(lift));
    // A small swirl while in flight, gone on arrival.
    float flight = lift * (1.0 - lift) * 4.0;
    p.xz += vec2(sin(seed * 41.0 + uTime * 2.3), cos(seed * 29.0 + uTime * 2.1)) * flight * 1.2;

    float appear = smoothstep(0.0, ${INTRO.appearS.toFixed(2)}, uTime - seed * 0.25);
    float fade = 1.0 - smoothstep(aTiming.y, aTiming.y + ${INTRO.pointFadeS.toFixed(2)}, uTime);
    float alpha = appear * fade;
    float size = kind == 0 ? 1.35 : kind == 1 ? 1.6 : kind == 2 ? 1.2 : 1.5;
    float boost = 1.0;
    if (kind == 3) {
      // The network shows only for its pulse: a flash, then a short glow.
      float since = uTime - aTiming.x;
      alpha = smoothstep(-0.08, 0.04, since) * fade;
      boost = 1.0 + 1.2 * exp(-max(since, 0.0) * 7.0);
      size *= 1.0 + 0.4 * exp(-max(since, 0.0) * 7.0);
    } else {
      // Arriving dots flash briefly.
      float landed = uTime - aTiming.x - ${INTRO.pointRiseS.toFixed(2)} * 0.6;
      boost = 1.0 + 1.3 * step(0.0, landed) * exp(-landed * 5.0);
    }
    vColor = aColor * boost;
    vAlpha = alpha;

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(size * uPixels / -mv.z, 1.8, 9.0);
    if (alpha <= 0.002) gl_PointSize = 0.0;
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uLight;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float d = dot(q, q);
    if (d > 1.0) discard;
    // Bright core with a soft halo: a glow without a bloom pass.
    float glow = 0.9 * exp(-d * 3.0) + 0.3 * exp(-d * 1.1);
    // Divide out the intro grade (openingGrade.ts) so the dots keep their light.
    gl_FragColor = vec4(vColor * glow * vAlpha / uLight, 1.0);
  }
`;

interface OpeningPointsProps {
  buildings: Building[];
  ground?: Ground;
  graph: CampusGraph;
  /** Time for the camera to tilt into the 3D view. */
  onGlide: () => void;
  /** Time for the panel and controls. */
  onReveal: () => void;
  /** The opening is over: unmount it. */
  onDone: () => void;
}

/**
 * Plays the opening (opening.ts): drives the shared clock and draws the
 * dots. The massing and the grade read the same clock.
 */
export function OpeningPoints({
  buildings,
  ground,
  graph,
  onGlide,
  onReveal,
  onDone,
}: OpeningPointsProps) {
  const size = useThree((s) => s.size);
  const camera = useThree((s) => s.camera) as PerspectiveCamera;
  const gl = useThree((s) => s.gl);
  const phone = size.width < 768;

  // Sampled once: later data (ground arriving) must not restart the opening.
  const [points] = useState(() =>
    sampleIntroPoints(buildings, ground, graph, {
      budget: phone ? BUDGET.phone : BUDGET.desktop,
      seedOf,
    }),
  );

  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(points.position, 3));
    g.setAttribute('aStart', new Float32BufferAttribute(points.start, 3));
    g.setAttribute('aTiming', new Float32BufferAttribute(points.timing, 4));
    g.setAttribute('aColor', new Float32BufferAttribute(points.color, 3));
    return g;
  }, [points]);
  // The material keeps its own copies (R3F clones uniforms); they follow the
  // shared clock every frame.
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uLight: { value: 1 },
      uPixels: { value: 1 },
    }),
    [],
  );
  const material = useRef<ShaderMaterial>(null);
  useEffect(() => () => geometry.dispose(), [geometry]);

  const frames = useRef(0);
  const [held] = useState(heldAt);
  const speed = useRef(1);
  const fired = useRef({ glide: false, reveal: false, done: false });
  const drawing = useMemo(() => new Vector2(), []);

  // Any touch, scroll or key: play the rest quickly instead of cutting.
  useEffect(() => {
    const skip = () => {
      speed.current = SKIP_SPEED;
    };
    const options = { passive: true } as const;
    window.addEventListener('pointerdown', skip, options);
    window.addEventListener('wheel', skip, options);
    window.addEventListener('keydown', skip);
    return () => {
      window.removeEventListener('pointerdown', skip);
      window.removeEventListener('wheel', skip);
      window.removeEventListener('keydown', skip);
    };
  }, []);

  useFrame((_, delta) => {
    // Point size in pixels per metre at unit distance, on the drawing buffer.
    const m = material.current;
    if (m) {
      gl.getDrawingBufferSize(drawing);
      const fov = (camera.fov * Math.PI) / 180;
      m.uniforms.uPixels!.value = drawing.y / (2 * Math.tan(fov / 2));
    }

    if (frames.current < WARMUP_FRAMES) {
      frames.current++;
      if (m) {
        m.uniforms.uTime!.value = introClock.time.value;
        m.uniforms.uLight!.value = introClock.light.value;
      }
      return;
    }
    // A long frame (tab switch, a hitch) must not jump the animation.
    const t =
      held ?? introClock.time.value + Math.min(delta, 1 / 30) * speed.current;
    introClock.time.value = t;
    introClock.light.value = introLight(t);
    if (m) {
      m.uniforms.uTime!.value = t;
      m.uniforms.uLight!.value = introClock.light.value;
    }
    const f = fired.current;
    if (!f.glide && t >= INTRO.glideS) {
      f.glide = true;
      onGlide();
    }
    if (!f.reveal && t >= INTRO.revealS) {
      f.reveal = true;
      onReveal();
    }
    if (!f.done && t >= INTRO.doneS) {
      f.done = true;
      introClock.time.value = INTRO_OVER;
      introClock.light.value = 1;
      onDone();
    }
  });

  return (
    <points geometry={geometry} frustumCulled={false} renderOrder={20}>
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        transparent
        depthWrite={false}
        blending={AdditiveBlending}
      />
    </points>
  );
}
