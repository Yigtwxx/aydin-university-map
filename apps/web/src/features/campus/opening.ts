import { Uniform } from 'three';

import { openRing } from './geometry';
import type { Building } from './types';

/**
 * The opening of the map: the camera tilts down from straight above while
 * the buildings rise out of the ground in a wave from the campus outwards,
 * and the scene's light opens up to the live sky. One clock (seconds) drives
 * the massing (facadeMaterial.ts) and the grade (openingGrade.ts).
 */
export const INTRO = {
  /** First building (campus centre) starts to rise. */
  riseFromS: 0.2,
  /** Time for the rising wave to reach riseRadiusM. */
  riseSpanS: 1.5,
  riseRadiusM: 1250,
  /** < 1: the wave lingers on the campus, then sweeps out over the city. */
  risePow: 0.62,
  riseJitterS: 0.16,
  /** One building takes this long to come out of the ground. */
  riseDurS: 0.9,
  /** Scene light: a little dim at first, the live sky by the end. */
  lightFrom: 0.55,
  lightRiseFromS: 0,
  lightRiseToS: 2.0,
  /** The camera starts tilting down into the 3D view. */
  glideS: 0.1,
  /** Panel, controls and labels come in. */
  revealS: 2.2,
  /** Every building stands; the opening unmounts. */
  doneS: 2.9,
} as const;

/** Clock value at which every building stands (no opening, or it is over). */
export const INTRO_OVER = 1e4;

/**
 * The opening's clock, shared as uniforms by the massing and the grade. One
 * map per page.
 */
export const introClock = {
  /** Seconds since the opening started. */
  time: new Uniform(INTRO_OVER),
  /** Scene light: INTRO.lightFrom .. 1. */
  light: new Uniform(1),
};

/** Sets the clock up for a scene that plays the opening or skips it. */
export function resetIntroClock(playing: boolean): void {
  introClock.time.value = playing ? 0 : INTRO_OVER;
  introClock.light.value = playing ? INTRO.lightFrom : 1;
}

export function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/** Scene light (INTRO.lightFrom .. 1) at intro time `t`. */
export function introLight(t: number): number {
  const k = smoothstep(INTRO.lightRiseFromS, INTRO.lightRiseToS, t);
  return INTRO.lightFrom + (1 - INTRO.lightFrom) * k;
}

export function centroid(outline: [number, number][]): [number, number] {
  const ring = openRing(outline);
  let e = 0;
  let n = 0;
  for (const [x, y] of ring) {
    e += x;
    n += y;
  }
  return ring.length ? [e / ring.length, n / ring.length] : [0, 0];
}

/** Centre of the campus buildings (ENU), where the wave starts. */
export function introOrigin(buildings: Building[]): [number, number] {
  let e = 0;
  let n = 0;
  let count = 0;
  for (const b of buildings) {
    if (!b.campus) continue;
    const [ce, cn] = centroid(b.outline);
    e += ce;
    n += cn;
    count++;
  }
  return count ? [e / count, n / count] : [0, 0];
}

/** When the building at `distanceM` from the origin starts to rise (s). */
export function riseStart(distanceM: number, seed: number): number {
  const share = Math.min(1, Math.max(0, distanceM / INTRO.riseRadiusM));
  return (
    INTRO.riseFromS +
    INTRO.riseSpanS * share ** INTRO.risePow +
    seed * INTRO.riseJitterS
  );
}
