import { describe, expect, it } from 'vitest';

import { INTRO, introLight, introOrigin, riseStart } from './opening';
import type { Building } from './types';

const square = (e: number, n: number, size: number): [number, number][] => [
  [e, n],
  [e + size, n],
  [e + size, n + size],
  [e, n + size],
  [e, n],
];

const building = (
  id: string,
  e: number,
  n: number,
  campus: boolean,
): Building => ({
  id,
  name: null,
  campus,
  height_m: 12,
  outline: square(e, n, 20),
});

describe('opening timeline', () => {
  it('raises the campus first and the far city last', () => {
    expect(riseStart(0, 0)).toBe(INTRO.riseFromS);
    expect(riseStart(200, 0)).toBeLessThan(riseStart(800, 0));
    expect(riseStart(INTRO.riseRadiusM * 4, 0)).toBeCloseTo(
      INTRO.riseFromS + INTRO.riseSpanS,
    );
  });

  it('has every building standing before the opening unmounts', () => {
    const last = riseStart(INTRO.riseRadiusM, 1) + INTRO.riseDurS;
    expect(last).toBeLessThan(INTRO.doneS);
  });

  it('brings the chrome in after the campus has risen', () => {
    const campus = riseStart(250, 1) + INTRO.riseDurS;
    expect(campus).toBeLessThan(INTRO.revealS);
  });

  it('opens the light up to the live sky', () => {
    expect(introLight(0)).toBeCloseTo(INTRO.lightFrom);
    expect(introLight(INTRO.lightRiseToS)).toBe(1);
    expect(introLight(1.2)).toBeGreaterThan(introLight(0.6));
  });

  it('starts the wave at the centre of the campus buildings', () => {
    const buildings = [
      building('way/1', 0, 0, true),
      building('way/2', 300, 0, false),
    ];
    expect(introOrigin(buildings)).toEqual([10, 10]);
  });
});
