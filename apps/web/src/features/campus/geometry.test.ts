import { describe, expect, it } from 'vitest';

import { Color } from 'three';

import { extrudeBuildings, openRing, paintWallsAndRoofs } from './geometry';
import type { Building } from './types';

const square: Building = {
  id: 'way/1',
  name: 'A',
  campus: true,
  height_m: 12,
  outline: [
    [0, 0],
    [10, 0],
    [10, 10],
    [0, 10],
    [0, 0],
  ],
};

describe('openRing', () => {
  it('drops the duplicated closing vertex', () => {
    expect(openRing(square.outline)).toHaveLength(4);
  });

  it('keeps rings that are already open', () => {
    expect(openRing(square.outline.slice(0, 4))).toHaveLength(4);
  });
});

describe('extrudeBuildings', () => {
  it('maps north to negative z and height to y', () => {
    const geometry = extrudeBuildings([square]);
    expect(geometry).toBeDefined();
    geometry!.computeBoundingBox();
    const box = geometry!.boundingBox!;
    expect(box.min.y).toBeCloseTo(0);
    expect(box.max.y).toBeCloseTo(12);
    expect(box.min.z).toBeCloseTo(-10);
    expect(box.max.z).toBeCloseTo(0);
    expect(box.max.x).toBeCloseTo(10);
  });

  it('returns undefined when nothing can be extruded', () => {
    expect(
      extrudeBuildings([{ ...square, outline: [[0, 0]] }]),
    ).toBeUndefined();
  });
});

describe('paintWallsAndRoofs', () => {
  it('colours upward faces as roof and the rest as wall', () => {
    const geometry = extrudeBuildings([square])!;
    const wall = new Color('#ff0000');
    const roof = new Color('#0000ff');
    paintWallsAndRoofs(geometry, wall, roof);
    const normals = geometry.getAttribute('normal');
    const colors = geometry.getAttribute('color');
    for (let i = 0; i < normals.count; i++) {
      const expected = normals.getY(i) > 0.5 ? roof : wall;
      expect(colors.getX(i)).toBeCloseTo(expected.r);
      expect(colors.getZ(i)).toBeCloseTo(expected.b);
    }
  });
});
