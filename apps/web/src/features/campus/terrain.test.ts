import { describe, expect, it } from 'vitest';

import { EMPTY_FURNITURE, type Furniture } from './furniture';
import {
  createTerrain,
  FLAT_TERRAIN,
  standingHeight,
  terrainOf,
} from './terrain';

const square = (x0: number, y0: number, size: number): [number, number][] => [
  [x0, y0],
  [x0 + size, y0],
  [x0 + size, y0 + size],
  [x0, y0 + size],
];

const furniture = (extra: Partial<Furniture>): Furniture => ({
  ...EMPTY_FURNITURE,
  ...extra,
});

describe('createTerrain', () => {
  it('is flat without terraces or flights', () => {
    const terrain = createTerrain(EMPTY_FURNITURE);
    expect(terrain.flat).toBe(true);
    expect(terrain.heightAt(12, -40)).toBe(0);
  });

  it('stands on a terrace inside its outline and on the street outside', () => {
    const terrain = createTerrain(
      furniture({
        terraces: [
          { id: 'square', outline: square(0, 0, 30), z_m: 1.5, edge: 'wall' },
        ],
      }),
    );
    expect(terrain.flat).toBe(false);
    expect(terrain.heightAt(15, 15)).toBe(1.5);
    expect(terrain.heightAt(0.2, 29.8)).toBe(1.5);
    expect(terrain.heightAt(-0.5, 15)).toBe(0);
    expect(terrain.heightAt(40, 40)).toBe(0);
  });

  it('accepts a closed, clockwise outline', () => {
    const ring = [...square(0, 0, 10)].reverse();
    const terrain = createTerrain(
      furniture({
        terraces: [
          { id: 't', outline: [...ring, ring[0]!], z_m: 2, edge: 'kerb' },
        ],
      }),
    );
    expect(terrain.heightAt(5, 5)).toBe(2);
    expect(terrain.terraces[0]!.ring).toHaveLength(4);
  });

  it('takes the innermost of nested terraces and cuts it out of the outer top', () => {
    const terrain = createTerrain(
      furniture({
        terraces: [
          { id: 'square', outline: square(0, 0, 30), z_m: 1.5, edge: 'wall' },
          { id: 'dais', outline: square(10, 10, 5), z_m: 2.8, edge: 'wall' },
        ],
      }),
    );
    expect(terrain.heightAt(12, 12)).toBe(2.8);
    expect(terrain.heightAt(5, 5)).toBe(1.5);
    const [outer, inner] = terrain.terraces;
    expect(inner!.parent).toBe(0);
    expect(inner!.surround).toBe(1.5);
    expect(outer!.holes).toHaveLength(1);
    // The outer top's triangles cover its area less the hole.
    let area = 0;
    const t = outer!.triangles;
    for (let i = 0; i < t.length; i += 6)
      area +=
        Math.abs(
          (t[i + 2]! - t[i]!) * (t[i + 5]! - t[i + 1]!) -
            (t[i + 4]! - t[i]!) * (t[i + 3]! - t[i + 1]!),
        ) / 2;
    expect(area).toBeCloseTo(900 - 25);
  });

  it('interpolates along a flight of stairs, and only within its width', () => {
    const terrain = createTerrain(
      furniture({
        terraces: [
          { id: 'square', outline: square(0, 0, 30), z_m: 1.5, edge: 'wall' },
        ],
        stairs: [
          {
            id: 'flight',
            foot: [-4, 10],
            top: [0, 10],
            width_m: 3,
            steps: 10,
            base_z: 0,
            rise_m: 1.5,
            railings: 'both',
          },
        ],
      }),
    );
    expect(terrain.heightAt(-4, 10)).toBeCloseTo(0);
    expect(terrain.heightAt(-2, 10)).toBeCloseTo(0.75);
    expect(terrain.heightAt(-1, 11.4)).toBeCloseTo(1.125);
    expect(terrain.heightAt(0, 10)).toBeCloseTo(1.5);
    // Beside the flight: the street.
    expect(terrain.heightAt(-2, 12)).toBe(0);
    // Past its top: the terrace.
    expect(terrain.heightAt(1, 10)).toBe(1.5);
  });

  it('falls away down a slope-edged terrace bank', () => {
    const terrain = createTerrain(
      furniture({
        terraces: [
          { id: 'lawn', outline: square(0, 0, 20), z_m: 1, edge: 'slope' },
        ],
      }),
    );
    const bank = terrain.terraces[0]!.bank;
    expect(bank).toBeCloseTo(1.8);
    expect(terrain.heightAt(10, 10)).toBe(1);
    expect(terrain.heightAt(-bank / 2, 10)).toBeCloseTo(0.5);
    expect(terrain.heightAt(-bank - 0.1, 10)).toBe(0);
  });
});

describe('terrainOf', () => {
  it('is flat before the furniture loads and built once per file', () => {
    expect(terrainOf(undefined)).toBe(FLAT_TERRAIN);
    const data = furniture({
      terraces: [{ id: 't', outline: square(0, 0, 4), z_m: 1, edge: 'wall' }],
    });
    expect(terrainOf(data)).toBe(terrainOf(data));
  });
});

describe('standingHeight', () => {
  const terrain = createTerrain(
    furniture({
      terraces: [
        { id: 't', outline: square(0, 0, 10), z_m: 1.5, edge: 'wall' },
      ],
    }),
  );
  it('puts an object without its own height on the ground there', () => {
    expect(standingHeight(terrain, 0, [5, 5])).toBe(1.5);
    expect(standingHeight(terrain, 0, [20, 5])).toBe(0);
  });
  it('keeps an explicit height', () => {
    expect(standingHeight(terrain, 0.4, [5, 5])).toBe(0.4);
  });
});
