import { describe, expect, it } from 'vitest';

import { bearingDeg, compassIndex, enuToWorld, yawForBearing } from './coords';

describe('enuToWorld', () => {
  it('maps north to negative z and up to y', () => {
    expect(enuToWorld(3, 5, 2)).toEqual([3, 2, -5]);
  });
});

describe('bearingDeg', () => {
  it.each([
    [[0, 1], 0],
    [[1, 0], 90],
    [[0, -1], 180],
    [[-1, 0], 270],
  ] as const)('points towards %j at %d degrees', (to, expected) => {
    expect(bearingDeg([0, 0], [to[0], to[1]])).toBeCloseTo(expected);
  });
});

describe('yawForBearing', () => {
  it('is zero when the target lies straight ahead of the front face', () => {
    expect(yawForBearing(120, 120)).toBeCloseTo(0);
  });

  it('wraps negative differences into [0, 2π)', () => {
    expect(yawForBearing(10, 100)).toBeCloseTo((270 * Math.PI) / 180);
  });
});

describe('compassIndex', () => {
  it.each([
    [0, 0],
    [44, 1],
    [90, 2],
    [350, 0],
    [-90, 6],
  ])('maps %d° to index %d', (bearing, index) => {
    expect(compassIndex(bearing)).toBe(index);
  });
});
