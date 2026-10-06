import { describe, expect, it } from 'vitest';

import { lineLength, ribbonGeometry } from './ribbon';

function vertices(points: [number, number][], width: number) {
  const geometry = ribbonGeometry([{ points, width }])!;
  const position = geometry.getAttribute('position');
  const uv = geometry.getAttribute('uv');
  return Array.from({ length: position.count }, (_, i) => ({
    x: position.getX(i),
    y: position.getY(i),
    z: position.getZ(i),
    along: uv.getX(i),
    across: uv.getY(i),
  }));
}

describe('ribbonGeometry', () => {
  it('builds a strip of the requested width along a straight line', () => {
    const v = vertices(
      [
        [0, 0],
        [10, 0],
      ],
      4,
    );
    expect(v).toHaveLength(4);
    // Heading east, the left edge is to the north (world -z).
    expect(v[0]).toMatchObject({ x: 0, z: -2, along: 0, across: 0 });
    expect(v[1]).toMatchObject({ x: 0, z: 2, across: 1 });
    expect(v[3]!.along).toBeCloseTo(10);
  });

  it('keeps the width through a right-angle corner with a miter join', () => {
    const v = vertices(
      [
        [0, 0],
        [10, 0],
        [10, 10],
      ],
      2,
    );
    // Corner vertices sit on the diagonal, √2 × half-width from the centre.
    const outer = v[3]!;
    expect(Math.hypot(outer.x - 10, outer.z)).toBeCloseTo(Math.SQRT2);
    expect(v[5]!.along).toBeCloseTo(20);
  });

  it('clamps the miter of a hairpin so it does not spike', () => {
    const v = vertices(
      [
        [0, 0],
        [10, 0],
        [0, 0.5],
      ],
      2,
    );
    for (const p of v.slice(2, 4)) {
      expect(Math.hypot(p.x - 10, p.z)).toBeLessThanOrEqual(2.5 + 1e-6);
    }
  });

  it('skips degenerate lines and returns undefined when nothing is left', () => {
    expect(
      ribbonGeometry([
        {
          points: [
            [1, 1],
            [1, 1],
          ],
          width: 3,
        },
      ]),
    ).toBeUndefined();
  });

  it('lies at the requested height', () => {
    const geometry = ribbonGeometry(
      [
        {
          points: [
            [0, 0],
            [0, 5],
          ],
          width: 1,
        },
      ],
      0.3,
    )!;
    expect(geometry.getAttribute('position').getY(0)).toBeCloseTo(0.3);
  });
});

describe('lineLength', () => {
  it('sums segment lengths', () => {
    expect(
      lineLength([
        [0, 0],
        [3, 4],
        [3, 10],
      ]),
    ).toBeCloseTo(11);
  });
});
