import { describe, expect, it } from 'vitest';

import { sunkenOpenings } from './sunken';
import { createTerrain } from './terrain';

const square = (x: number, size = 10): [number, number][] => [
  [x, 0],
  [x + size, 0],
  [x + size, size],
  [x, size],
];

describe('sunkenOpenings', () => {
  it('opens only the terraces sunk below the street datum', () => {
    const terrain = createTerrain({
      schema_version: 1,
      terraces: [
        { id: 'raised', outline: square(0), z_m: 3, edge: 'wall' },
        { id: 'garden', outline: square(40), z_m: -2.9, edge: 'wall' },
        // Sunk into a raised terrace: its surround is not the street.
        { id: 'pool', outline: square(2, 4), z_m: 1, edge: 'wall' },
      ],
      stairs: [],
      ramps: [],
      railings: [],
      items: [],
      seating: [],
      walkways: [],
    });
    const openings = sunkenOpenings(terrain.terraces);
    expect(openings).toHaveLength(1);
    expect(Math.min(...openings[0]!.map(([e]) => e))).toBe(40);
  });
});
