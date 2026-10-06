'use client';

import { Sky, Stars } from '@react-three/drei';
import { useMemo } from 'react';

import type { SkyPhase } from '@/features/environment/hooks';
import type { Sun } from '@/features/environment/sun';
import type { Condition } from '@/features/environment/weather';

import { enuToWorld } from './coords';

const SUN_DISTANCE = 700;

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
    sunIntensity: 3.0,
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
      return { light: 0.6, fogScale: 0.85 };
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

  const fogNear = 900 * dim.fogScale;
  const fogFar = 3400 * dim.fogScale;

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
      {/* Clouds trade direct sun for diffuse skylight, so the map stays bright. */}
      <hemisphereLight
        args={[
          look.hemiSky,
          look.hemiGround,
          look.hemiIntensity * (1 + (1 - dim.light) * 0.9),
        ]}
      />
      <directionalLight
        position={sunPosition}
        intensity={look.sunIntensity * dim.light}
        color={look.sunColor}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-420}
        shadow-camera-right={420}
        shadow-camera-top={420}
        shadow-camera-bottom={-420}
        shadow-camera-far={2200}
        shadow-bias={-0.0004}
        shadow-normalBias={0.6}
      />
    </>
  );
}
