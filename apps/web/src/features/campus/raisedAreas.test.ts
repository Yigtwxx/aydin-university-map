import { describe, expect, it } from 'vitest';

import { raisedAreaGeometry } from './raisedAreas';

const square = (e: number): [number, number][] => [
  [e, 0],
  [e + 4, 0],
  [e + 4, 4],
  [e, 4],
];

describe('raisedAreaGeometry', () => {
  it('draws every area, not just the first two', () => {
    const g = raisedAreaGeometry(
      [square(0), square(10), square(20)],
      { top: '#00ff00', side: '#ffff00', depth: 0.15 },
      () => 0,
    )!;
    // One merged mesh, no per-area groups that would each want a material.
    expect(g.groups).toHaveLength(0);
    const xs = new Set<number>();
    const pos = g.getAttribute('position');
    for (let i = 0; i < pos.count; i++) xs.add(Math.round(pos.getX(i)));
    expect([...xs].sort((a, b) => a - b)).toEqual([0, 4, 10, 14, 20, 24]);
  });

  it('colours the caps like the top and the sides like the kerb', () => {
    const g = raisedAreaGeometry(
      [square(0)],
      { top: '#00ff00', side: '#ffff00', depth: 0.15 },
      () => 2,
    )!;
    const pos = g.getAttribute('position');
    const col = g.getAttribute('color');
    let topGreen = 0;
    let sideYellow = 0;
    for (let i = 0; i < pos.count; i += 3) {
      // A triangle whose corners share one height is a cap.
      const flat =
        pos.getY(i) === pos.getY(i + 1) && pos.getY(i) === pos.getY(i + 2);
      if (flat && col.getX(i) === 0 && col.getY(i) === 1) topGreen++;
      if (!flat && col.getX(i) === 1 && col.getY(i) === 1) sideYellow++;
    }
    expect(topGreen).toBeGreaterThan(0);
    expect(sideYellow).toBeGreaterThan(0);
    // Standing on the ground under it.
    expect(
      Math.min(...Array.from(pos.array).filter((_, k) => k % 3 === 1)),
    ).toBeCloseTo(2);
  });
});
