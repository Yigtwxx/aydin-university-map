import { describe, expect, it } from 'vitest';

import { buildMassing, seedOf, STYLE_INDEX } from './massing';
import type { Building } from './types';

const square = (size: number): [number, number][] => [
  [0, 0],
  [size, 0],
  [size, size],
  [0, size],
  [0, 0],
];

describe('buildMassing', () => {
  it('writes the facade attributes the shader reads', () => {
    const g = buildMassing([
      {
        id: 'way/1',
        name: null,
        campus: false,
        height_m: 15,
        outline: square(20),
        style: 'apartment',
        levels: 5,
        roof: { shape: 'flat' },
      },
    ]);
    expect(g).toBeDefined();
    for (const name of [
      'position',
      'normal',
      'color',
      'aWall',
      'aMeta',
      'aFlags',
      'aRise',
    ])
      expect(g!.getAttribute(name)).toBeDefined();
    const meta = g!.getAttribute('aMeta');
    expect(meta.getX(0)).toBe(STYLE_INDEX.apartment);
    expect(meta.getZ(0)).toBe(5);
  });

  it('puts a hipped roof above the eaves', () => {
    const building: Building = {
      id: 'way/2',
      name: null,
      campus: false,
      height_m: 9,
      outline: square(10),
      style: 'house',
      roof: {
        shape: 'hipped',
        obb: square(10).slice(0, 4),
        rise: 2,
        overhang: 0.4,
      },
    };
    const g = buildMassing([building])!;
    g.computeBoundingBox();
    expect(g.boundingBox!.max.y).toBeCloseTo(11, 5);
  });

  it('builds a mosque with a dome and a minaret taller than the walls', () => {
    const g = buildMassing([
      {
        id: 'way/3',
        name: 'Cami',
        campus: false,
        height_m: 9,
        outline: square(18),
        style: 'worship',
        roof: {
          shape: 'dome',
          centre: [9, 9],
          radius: 7,
          minaret: [0, 0],
          minaret_m: 30,
        },
      },
    ])!;
    g.computeBoundingBox();
    expect(g.boundingBox!.max.y).toBeCloseTo(30, 5);
  });
});

describe('seedOf', () => {
  it('is stable and within 0..1', () => {
    expect(seedOf('way/42')).toBe(seedOf('way/42'));
    expect(seedOf('way/42')).toBeGreaterThanOrEqual(0);
    expect(seedOf('way/42')).toBeLessThan(1);
    expect(seedOf('way/42')).not.toBe(seedOf('way/43'));
  });
});
