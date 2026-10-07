import { BufferGeometry, Float32BufferAttribute } from 'three';
import { describe, expect, it } from 'vitest';

import { clipConvex, liftOntoTerraces } from './clip';
import { EMPTY_FURNITURE } from './furniture';
import { ribbonGeometry } from './ribbon';
import { createTerrain } from './terrain';

function areaOf(geometry: BufferGeometry): number {
  const p = geometry.getAttribute('position');
  let area = 0;
  for (let i = 0; i < p.count; i += 3) {
    const ax = p.getX(i);
    const az = p.getZ(i);
    const bx = p.getX(i + 1) - ax;
    const bz = p.getZ(i + 1) - az;
    const cx = p.getX(i + 2) - ax;
    const cz = p.getZ(i + 2) - az;
    area += Math.abs(bx * cz - bz * cx) / 2;
  }
  return area;
}

const terrain = createTerrain({
  ...EMPTY_FURNITURE,
  terraces: [
    {
      id: 'square',
      // An L-shaped terrace: concave, so clipping must not assume convexity.
      outline: [
        [0, 0],
        [20, 0],
        [20, 10],
        [10, 10],
        [10, 20],
        [0, 20],
      ],
      z_m: 1.5,
      edge: 'wall',
    },
  ],
});

describe('clipConvex', () => {
  it('keeps the part of a polygon inside a convex window', () => {
    const out = clipConvex(
      [
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
      ],
      [
        [0, 0],
        [2, 0],
        [0, 2],
      ],
    );
    expect(out.length).toBeGreaterThanOrEqual(3);
    for (const [x, y] of out) {
      expect(x).toBeGreaterThanOrEqual(-1e-9);
      expect(y).toBeGreaterThanOrEqual(-1e-9);
    }
  });
});

describe('liftOntoTerraces', () => {
  it('lifts exactly the part of a path that crosses a terrace', () => {
    // A 2 m wide path heading north along east = 15: 10 m of it is on the
    // terrace (north 0..10), the rest is in the L's notch.
    const path = ribbonGeometry(
      [
        {
          points: [
            [15, -5],
            [15, 25],
          ],
          width: 2,
        },
      ],
      0.05,
    )!;
    const lifted = liftOntoTerraces(path, terrain.terraces, 0.05)!;
    expect(areaOf(lifted)).toBeCloseTo(20, 4);
    const position = lifted.getAttribute('position');
    const normal = lifted.getAttribute('normal');
    for (let i = 0; i < position.count; i++) {
      expect(position.getY(i)).toBeCloseTo(1.55);
      expect(normal.getY(i)).toBe(1);
      // Within the terrace's footprint (world z = -north).
      expect(-position.getZ(i)).toBeGreaterThanOrEqual(-1e-6);
      expect(-position.getZ(i)).toBeLessThanOrEqual(10 + 1e-6);
    }
    // Every lifted triangle faces up.
    for (let i = 0; i < position.count; i += 3) {
      const ax = position.getX(i);
      const az = position.getZ(i);
      const ny =
        (position.getZ(i + 1) - az) * (position.getX(i + 2) - ax) -
        (position.getX(i + 1) - ax) * (position.getZ(i + 2) - az);
      expect(ny).toBeGreaterThan(0);
    }
  });

  it('returns nothing for a layer off every terrace', () => {
    const geometry = new BufferGeometry();
    geometry.setAttribute(
      'position',
      new Float32BufferAttribute([50, 0, -50, 52, 0, -50, 50, 0, -52], 3),
    );
    expect(liftOntoTerraces(geometry, terrain.terraces, 0.05)).toBeUndefined();
    expect(liftOntoTerraces(geometry, [], 0.05)).toBeUndefined();
  });
});
