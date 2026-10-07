import type { SkyPhase } from './hooks';
import type { Condition } from './weather';

/** Weathers that share a sky in the weather sheet. */
export type SkyKind =
  'clear' | 'partly' | 'overcast' | 'fog' | 'rain' | 'storm' | 'snow';

export function skyKindOf(condition: Condition | undefined): SkyKind {
  switch (condition) {
    case undefined:
    case 'clear':
    case 'mainlyClear':
      return 'clear';
    case 'partlyCloudy':
      return 'partly';
    case 'overcast':
      return 'overcast';
    case 'fog':
      return 'fog';
    case 'drizzle':
    case 'rain':
    case 'showers':
      return 'rain';
    case 'storm':
      return 'storm';
    case 'snow':
      return 'snow';
  }
}

/**
 * Top and bottom of the sheet's sky, per weather and time of day. Every stop
 * keeps the sheet's secondary text (90% white) at 4.5:1 or better
 * (skyTheme.test.ts), so the small print stays legible whatever the sky.
 */
export const SKY_GRADIENTS: Record<
  SkyKind,
  Record<SkyPhase, readonly [string, string]>
> = {
  clear: {
    day: ['#1b52a7', '#2d6cbf'],
    golden: ['#284383', '#a95636'],
    twilight: ['#1a2350', '#4b3a6b'],
    night: ['#091331', '#1b2b55'],
  },
  partly: {
    day: ['#1b3c65', '#2c4b72'],
    golden: ['#253153', '#653d30'],
    twilight: ['#1f2647', '#463f61'],
    night: ['#111a33', '#26334f'],
  },
  overcast: {
    day: ['#3d4856', '#525d68'],
    golden: ['#3f4153', '#685857'],
    twilight: ['#262b3a', '#3c4152'],
    night: ['#161b26', '#2a303d'],
  },
  fog: {
    day: ['#3a4249', '#474b52'],
    golden: ['#3b3b45', '#504a4b'],
    twilight: ['#2c303c', '#454a57'],
    night: ['#1c212b', '#323844'],
  },
  rain: {
    day: ['#314152', '#4d5e6f'],
    golden: ['#3a3f55', '#5f5868'],
    twilight: ['#1f2533', '#343c4d'],
    night: ['#0f141d', '#222a37'],
  },
  storm: {
    day: ['#2a2f42', '#474c61'],
    golden: ['#2d2c40', '#55465a'],
    twilight: ['#191c29', '#2e3242'],
    night: ['#0b0d14', '#1c1f2a'],
  },
  snow: {
    day: ['#374c63', '#475e76'],
    golden: ['#3b4660', '#63586c'],
    twilight: ['#283048', '#434c66'],
    night: ['#161d2e', '#2c3650'],
  },
};

/**
 * The most white the cloud and fog layers may add anywhere, all layers
 * together (see `.sky-cloud-*` and `.sky-fog-*` in globals.css). Fair-weather
 * puffs and fog need more to read, so they get more, on a darker sky. The palette is tested to
 * keep white text legible with it on top.
 */
export const SKY_OVERLAY_PEAK: Record<SkyKind, number> = {
  clear: 0,
  partly: 0.25,
  overcast: 0.16,
  fog: 0.24,
  rain: 0.16,
  storm: 0.16,
  snow: 0.16,
};

/** What is drawn over the gradient. */
export interface SkyArt {
  glow?: 'sun' | 'sunset' | 'moon';
  stars: boolean;
  /** Cloud drawn over the sky: separate puffs, or a broken deck. */
  clouds?: 'cumulus' | 'stratus';
  fog: boolean;
  precipitation?: 'rain' | 'snow';
}

const CLOUDS: Record<SkyKind, SkyArt['clouds']> = {
  clear: undefined,
  partly: 'cumulus',
  overcast: 'stratus',
  fog: undefined,
  rain: 'stratus',
  storm: 'stratus',
  snow: 'stratus',
};

export function skyArtOf(kind: SkyKind, phase: SkyPhase): SkyArt {
  const dark = phase === 'night' || phase === 'twilight';
  const open = kind === 'clear' || kind === 'partly';
  return {
    glow: open
      ? dark
        ? 'moon'
        : phase === 'golden'
          ? 'sunset'
          : 'sun'
      : undefined,
    stars: open && dark,
    clouds: CLOUDS[kind],
    fog: kind === 'fog',
    precipitation:
      kind === 'rain' || kind === 'storm'
        ? 'rain'
        : kind === 'snow'
          ? 'snow'
          : undefined,
  };
}

/** How hard it rains or snows, 0–1, for the falling particles. */
export function precipitationIntensity(condition: Condition | undefined) {
  switch (condition) {
    case 'drizzle':
      return 0.4;
    case 'rain':
      return 0.7;
    case 'showers':
    case 'storm':
      return 1;
    default:
      return 0.75;
  }
}

/** Slant of the rain without a wind reading: a light breeze. */
const CALM_SLANT = 0.12;

/**
 * Sideways travel of rain per px of fall, from the wind: positive drifts
 * right (east). The sheet is a screen, not the map, so east is right.
 */
export function rainSlant(wind?: { speedKmh: number; fromDeg: number }) {
  if (!wind) return CALM_SLANT;
  const toEast = -Math.sin((wind.fromDeg * Math.PI) / 180);
  const strength = Math.min(1, Math.max(0.2, wind.speedKmh / 40));
  return toEast * strength * 0.42;
}
