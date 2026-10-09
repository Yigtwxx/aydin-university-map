import { describe, expect, it } from 'vitest';

import { pointInRing } from './terrain';
import { crownGeometry, WOOD_SPACING_M, woodTrees } from './woodland';

const square: [number, number][] = [
  [0, 0],
  [130, 0],
  [130, 130],
  [0, 130],
  [0, 0],
];

describe('woodTrees', () => {
  it('plants about one tree per grid cell, all inside the wood', () => {
    const trees = woodTrees([square]);
    const cells = (130 / WOOD_SPACING_M) ** 2;
    expect(trees.length).toBeGreaterThan(cells * 0.8);
    expect(trees.length).toBeLessThanOrEqual(cells * 1.25);
    for (const [e, n] of trees) expect(pointInRing(e, n, square)).toBe(true);
  });

  it('gives every tree a height within the woods range', () => {
    for (const tree of woodTrees([square])) {
      expect(tree[2]).toBeGreaterThanOrEqual(7);
      expect(tree[2]).toBeLessThanOrEqual(12);
    }
  });

  it('plants the same trees for the same data', () => {
    expect(woodTrees([square])).toEqual(woodTrees([square]));
  });

  it('stops at the limit', () => {
    expect(woodTrees([square], WOOD_SPACING_M, 10)).toHaveLength(10);
  });

  it('ignores degenerate outlines', () => {
    expect(
      woodTrees([
        [
          [0, 0],
          [1, 1],
        ],
      ]),
    ).toEqual([]);
  });
});

describe('crownGeometry', () => {
  it('fits a crown of about unit radius, darker underneath', () => {
    const geometry = crownGeometry(1);
    geometry.computeBoundingBox();
    const box = geometry.boundingBox!;
    expect(box.max.y).toBeLessThanOrEqual(1.05);
    expect(box.min.y).toBeGreaterThan(-1);
    expect(Math.max(box.max.x, -box.min.x)).toBeLessThanOrEqual(1.05);
    const position = geometry.getAttribute('position');
    const color = geometry.getAttribute('color');
    let low = Infinity;
    let high = -Infinity;
    for (let i = 0; i < position.count; i++) {
      if (position.getY(i) < -0.5) low = Math.min(low, color.getX(i));
      if (position.getY(i) > 0.8) high = Math.max(high, color.getX(i));
    }
    expect(low).toBeLessThan(high);
  });

  it('is cheaper without subdivision', () => {
    expect(crownGeometry(0).getAttribute('position').count).toBeLessThan(
      crownGeometry(1).getAttribute('position').count,
    );
  });
});
