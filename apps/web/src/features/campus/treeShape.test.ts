import { describe, expect, it } from 'vitest';

import {
  DEFAULT_TREE_M,
  HEIGHT_JITTER,
  positionHash,
  treeShape,
  type TreeRecord,
} from './treeShape';

const spread = (count: number): TreeRecord[] =>
  Array.from({ length: count }, (_, i) => [i * 3.7 - 40, i * 1.3 + 5, 5.5]);

describe('treeShape', () => {
  it('keeps the height within the jitter of the record', () => {
    for (const tree of spread(200)) {
      const { height } = treeShape(tree);
      expect(height).toBeGreaterThanOrEqual(5.5 * (1 - HEIGHT_JITTER));
      expect(height).toBeLessThanOrEqual(5.5 * (1 + HEIGHT_JITTER));
    }
  });

  it('gives a campus tree a small crown', () => {
    const shapes = spread(200).map(treeShape);
    const radii = shapes.map((s) => s.crownRadius);
    expect(Math.min(...radii)).toBeGreaterThan(1.4);
    expect(Math.max(...radii)).toBeLessThan(2.8);
    const mean = radii.reduce((a, b) => a + b, 0) / radii.length;
    expect(mean).toBeGreaterThan(1.8);
    expect(mean).toBeLessThan(2.3);
  });

  it('sits the crown on the trunk and tops out at the height', () => {
    for (const tree of spread(50)) {
      const s = treeShape(tree);
      expect(s.crownY + s.crownHalfHeight).toBeCloseTo(s.height, 9);
      expect(s.trunkHeight).toBeCloseTo(s.crownY, 9);
      // Some bare trunk shows below the crown.
      expect(s.crownY - s.crownHalfHeight).toBeGreaterThan(0.25 * s.height);
    }
  });

  it('makes a smaller tree shorter and thinner in the trunk', () => {
    const small = treeShape([10, 10, 3]);
    const big = treeShape([10, 10, 8]);
    expect(small.trunkHeight).toBeLessThan(big.trunkHeight);
    expect(small.trunkRadius).toBeLessThan(big.trunkRadius);
    expect(small.crownRadius).toBeLessThan(big.crownRadius);
  });

  it('keys the variation on position, not order', () => {
    const a = treeShape([12.34, -56.78, 5.5]);
    const b = treeShape([12.34, -56.78, 5.5]);
    expect(a).toEqual(b);
    expect(treeShape([12.34, -56.78, 5.5]).height).not.toBe(
      treeShape([20.1, -56.78, 5.5]).height,
    );
    // Sub-centimetre noise in the export does not change the tree.
    expect(positionHash(12.34, -56.78, 1)).toBe(
      positionHash(12.341, -56.779, 1),
    );
  });

  it('falls back to the default height for a bare [east, north] record', () => {
    const { height } = treeShape([3, 4]);
    expect(height).toBeGreaterThanOrEqual(DEFAULT_TREE_M * (1 - HEIGHT_JITTER));
    expect(height).toBeLessThanOrEqual(DEFAULT_TREE_M * (1 + HEIGHT_JITTER));
  });
});
