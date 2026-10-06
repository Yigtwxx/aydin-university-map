import { describe, expect, it } from 'vitest';

import {
  chaikin,
  resample,
  routePolyline,
  simplify,
  smoothRoute,
} from './routeLine';
import type { GraphEdge, GraphNode } from './types';

const node = (id: string, e: number, n: number): GraphNode => ({
  id,
  kind: 'outdoor',
  lat: 0,
  lng: 0,
  alt_m: 0,
  enu: [e, n, 0],
  heading_deg: 0,
  label: { tr: id, en: id },
  area: { tr: '', en: '' },
  building: null,
});

describe('routePolyline', () => {
  it('follows an edge bend in either walking direction', () => {
    const a = node('a', 0, 0);
    const b = node('b', 10, 0);
    const edge: GraphEdge = {
      id: 'a|b',
      source: 'a',
      target: 'b',
      kind: 'outdoor',
      length_m: 14,
      path_enu: [
        [0, 0],
        [5, 5],
        [10, 0],
      ],
    };
    const edges = new Map([[edge.id, edge]]);
    expect(routePolyline([a, b], edges)).toEqual([
      [0, 0],
      [5, 5],
      [10, 0],
    ]);
    expect(routePolyline([b, a], edges)).toEqual([
      [10, 0],
      [5, 5],
      [0, 0],
    ]);
  });
});

describe('line smoothing', () => {
  it('simplify drops wobble but keeps real corners', () => {
    const line: [number, number][] = [
      [0, 0],
      [5, 0.3],
      [10, 0],
      [10, 10],
    ];
    expect(simplify(line, 0.6)).toEqual([
      [0, 0],
      [10, 0],
      [10, 10],
    ]);
  });

  it('chaikin keeps both ends and rounds the corner', () => {
    const out = chaikin(
      [
        [0, 0],
        [10, 0],
        [10, 10],
      ],
      2,
    );
    expect(out[0]).toEqual([0, 0]);
    expect(out[out.length - 1]).toEqual([10, 10]);
    expect(out.some(([x, y]) => x === 10 && y === 0)).toBe(false);
  });

  it('resample spaces points evenly and keeps the end', () => {
    const out = resample(
      [
        [0, 0],
        [10, 0],
      ],
      2,
    );
    expect(out).toHaveLength(6);
    expect(out[out.length - 1]).toEqual([10, 0]);
  });

  it('smoothRoute stays close to a right-angle corner', () => {
    const out = smoothRoute([
      [0, 0],
      [20, 0],
      [20, 20],
    ]);
    // The rounded corner cuts at most ~0.5 m inside the original vertex.
    const nearest = Math.min(...out.map(([x, y]) => Math.hypot(20 - x, y)));
    expect(nearest).toBeLessThan(0.6);
  });
});
