'use client';

import { Sky, Stars } from '@react-three/drei';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { type DirectionalLight, Vector3 } from 'three';

import type { SkyPhase } from '@/features/environment/hooks';
import type { Sun } from '@/features/environment/sun';
import type { Condition } from '@/features/environment/weather';

import { enuToWorld } from './coords';
import {
  SHADOW_HALF_MAX_M,
  SHADOW_MAP_PX,
  shadowHalfWidth,
  snapToTexel,
} from './shadowFit';

const SUN_DISTANCE = 700;
/** Share of the hemisphere fill kept next to the image-based sky light. */
const HEMI_SHARE = 0.5;

interface Lighting {
  sunColor: string;
  sunIntensity: number;
  hemiSky: string;
  hemiGround: string;
  hemiIntensity: number;
  fog: string;
  background?: string;
}

const BY_PHASE: Record<SkyPhase, Lighting> = {
  day: {
    sunColor: '#FFF4E2',
    // Tone mapping rolls the brightest paving off, so the sun can be a
    // little stronger against a dimmer sky fill: crisper light and shade.
    sunIntensity: 3.3,
    hemiSky: '#EAF2F7',
    hemiGround: '#B9AF99',
    hemiIntensity: 1.0,
    fog: '#DCE4EA',
  },
  golden: {
    sunColor: '#FFC98F',
    sunIntensity: 2.3,
    hemiSky: '#F4DCC4',
    hemiGround: '#9E8C74',
    hemiIntensity: 0.85,
    fog: '#E9D3BE',
  },
  twilight: {
    sunColor: '#9DB2E0',
    sunIntensity: 0.8,
    hemiSky: '#56688F',
    hemiGround: '#2B2E38',
    hemiIntensity: 1.05,
    fog: '#3A4762',
    background: '#33415E',
  },
  night: {
    sunColor: '#A9BEEA',
    sunIntensity: 0.7,
    hemiSky: '#3A4C70',
    hemiGround: '#1C2029',
    hemiIntensity: 1.05,
    fog: '#141C2B',
    background: '#0E1522',
  },
};

/** Overcast and rain flatten the light and pull the fog in. */
function weatherDim(condition?: Condition): {
  light: number;
  fogScale: number;
} {
  switch (condition) {
    case 'overcast':
      return { light: 0.72, fogScale: 0.85 };
    case 'fog':
      return { light: 0.5, fogScale: 0.3 };
    case 'drizzle':
    case 'rain':
    case 'showers':
    case 'snow':
      return { light: 0.5, fogScale: 0.6 };
    case 'storm':
      return { light: 0.4, fogScale: 0.5 };
    case 'partlyCloudy':
      return { light: 0.88, fogScale: 1 };
    default:
      return { light: 1, fogScale: 1 };
  }
}

/** Live sky: sun (or moon light), hemisphere fill, fog and stars at night. */
export function SkyRig({
  sun,
  phase,
  condition,
}: {
  sun: Sun;
  phase: SkyPhase;
  condition?: Condition;
}) {
  const look = BY_PHASE[phase];
  const dim = weatherDim(condition);
  const night = phase === 'night' || phase === 'twilight';

  const sunPosition = useMemo(() => {
    // At night the key light comes from high in the south-west (moonlight),
    // so buildings keep their shape instead of going flat.
    if (night) return enuToWorld(-260, -420, 520);
    const up = Math.max(sun.direction[2], 0.18);
    return enuToWorld(
      sun.direction[0] * SUN_DISTANCE,
      sun.direction[1] * SUN_DISTANCE,
      up * SUN_DISTANCE,
    );
  }, [sun, night]);

  // Haze starts past the neighbourhood so the campus stays crisp.
  const fogNear = 1300 * dim.fogScale;
  const fogFar = 4800 * dim.fogScale;

  return (
    <>
      <fog attach="fog" args={[look.fog, fogNear, fogFar]} />
      {look.background && (
        <color attach="background" args={[look.background]} />
      )}
      {!night && (
        <Sky
          distance={4500}
          sunPosition={sunPosition}
          turbidity={condition === 'overcast' ? 12 : 5.5}
          rayleigh={phase === 'golden' ? 2.4 : 1.3}
          mieCoefficient={0.004}
          mieDirectionalG={0.82}
        />
      )}
      {night && (
        <Stars
          radius={2400}
          depth={300}
          count={2600}
          factor={22}
          fade
          speed={0}
        />
      )}
      {/* Clouds trade direct sun for diffuse skylight, so the map stays
          bright. The sky environment (CampusScene) already adds ambient light,
          so the hemisphere only fills, keeping contrast in the shading. */}
      <hemisphereLight
        args={[
          look.hemiSky,
          look.hemiGround,
          look.hemiIntensity * HEMI_SHARE * (1 + (1 - dim.light) * 0.9),
        ]}
      />
      <SunLight
        direction={sunPosition}
        intensity={look.sunIntensity * dim.light}
        color={look.sunColor}
      />
    </>
  );
}

/** Shadow texels a surface is pushed along its normal before it is tested. */
const NORMAL_BIAS_TEXELS = 1.5;

/**
 * The sun (or moon) light. Its shadow frustum follows the point the camera
 * looks at and tightens as the camera comes down, so close up the benches,
 * lamps and trees throw crisp shadows; from afar it covers the campus.
 */
function SunLight({
  direction,
  intensity,
  color,
}: {
  direction: [number, number, number];
  intensity: number;
  color: string;
}) {
  const light = useRef<DirectionalLight>(null);
  const scene = useThree((s) => s.scene);
  // Scratch vectors and the frustum size last applied, kept across frames.
  const work = useRef({
    sun: new Vector3(),
    target: new Vector3(),
    snapped: new Vector3(),
    half: 0,
  });

  useEffect(() => {
    const target = light.current?.target;
    if (!target) return;
    scene.add(target);
    return () => {
      scene.remove(target);
    };
  }, [scene]);

  useFrame((state) => {
    const l = light.current;
    if (!l) return;
    const controls = state.controls as unknown as {
      getTarget?: (out: Vector3) => Vector3;
      distance?: number;
    } | null;
    const w = work.current;
    const { sun, target, snapped } = w;
    sun.set(...direction).normalize();
    if (controls?.getTarget) controls.getTarget(target);
    else target.set(0, 0, 0);
    target.y = 0;

    const half = shadowHalfWidth(controls?.distance ?? SHADOW_HALF_MAX_M * 2);
    const cam = l.shadow.camera;
    if (half !== w.half) {
      w.half = half;
      cam.left = -half;
      cam.right = half;
      cam.top = half;
      cam.bottom = -half;
      cam.updateProjectionMatrix();
      l.shadow.normalBias = ((2 * half) / SHADOW_MAP_PX) * NORMAL_BIAS_TEXELS;
    }
    snapToTexel(target, sun, (2 * half) / SHADOW_MAP_PX, snapped);
    l.target.position.copy(snapped);
    l.target.updateMatrixWorld();
    l.position.copy(snapped).addScaledVector(sun, SUN_DISTANCE);
  });

  return (
    <directionalLight
      ref={light}
      position={direction}
      intensity={intensity}
      color={color}
      castShadow
      shadow-mapSize={[SHADOW_MAP_PX, SHADOW_MAP_PX]}
      shadow-camera-left={-SHADOW_HALF_MAX_M}
      shadow-camera-right={SHADOW_HALF_MAX_M}
      shadow-camera-top={SHADOW_HALF_MAX_M}
      shadow-camera-bottom={-SHADOW_HALF_MAX_M}
      shadow-camera-far={2200}
      shadow-bias={-0.0004}
      shadow-normalBias={0.6}
    />
  );
}
