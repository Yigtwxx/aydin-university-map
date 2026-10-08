import { describe, expect, it } from 'vitest';

import { deckHeights } from './deckLift';
import type { Walkway } from './furniture';

// A footbridge 5 m up over the street: x 0..4, y 0..20; its panorama at (2, 10).
const BRIDGE: Walkway = {
  id: 'bridge',
  outline: [
    [0, 0],
    [4, 0],
    [4, 20],
    [0, 20],
  ],
  z_m: 5,
  spots: ['up'],
};
const spotAt = (id: string): [number, number] | undefined =>
  id === 'up' ? [2, 10] : undefined;

describe('deckHeights', () => {
  it('lifts the stretch that walks past the walkway panorama', () => {
    const route: [number, number][] = [
      [2, -5],
      [2, 2],
      [2, 10],
      [2, 18],
    ];
    expect(deckHeights(route, [BRIDGE], spotAt)).toEqual([undefined, 5, 5, 5]);
  });

  it('leaves a street route passing under the walkway on the ground', () => {
    const route: [number, number][] = [
      [-5, 3],
      [2, 3],
      [9, 3],
    ];
    expect(deckHeights(route, [BRIDGE], spotAt)).toEqual([
      undefined,
      undefined,
      undefined,
    ]);
  });

  it('keeps the street stretch down when the same route later climbs up', () => {
    const route: [number, number][] = [
      [2, 4], // under the bridge, 6 m from its panorama
      [6, 4],
      [6, 10],
      [2, 10], // up on it
    ];
    expect(deckHeights(route, [BRIDGE], spotAt)).toEqual([
      undefined,
      undefined,
      undefined,
      5,
    ]);
  });

  it('ignores a walkway whose panoramas are not in the graph', () => {
    const route: [number, number][] = [[2, 10]];
    expect(deckHeights(route, [BRIDGE], () => undefined)).toEqual([undefined]);
  });
});
