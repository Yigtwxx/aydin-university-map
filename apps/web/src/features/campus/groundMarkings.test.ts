import { describe, expect, it } from 'vitest';

import {
  crossingsOf,
  laneLines,
  MARKING,
  pitchLines,
  roadClass,
  segmentCrossing,
  zebraGeometry,
} from './groundMarkings';
import type { Ground } from './types';

type Way = Ground['ways'][number];
const way = (kind: string, line: [number, number][], width_m = 8): Way => ({
  kind,
  name: null,
  width_m,
  line,
});

describe('roadClass', () => {
  it('sorts streets and paths', () => {
    expect(roadClass('trunk')).toBe('major');
    expect(roadClass('residential')).toBe('minor');
    expect(roadClass('footway')).toBe('path');
  });
});

describe('segmentCrossing', () => {
  it('finds the crossing inside both segments', () => {
    expect(segmentCrossing([0, 0], [10, 0], [5, -5], [5, 5])).toEqual([5, 0]);
  });

  it('ignores a segment that only touches the other at its end', () => {
    expect(segmentCrossing([0, 0], [10, 0], [5, 0], [5, 5])).toBeUndefined();
  });

  it('ignores parallel segments', () => {
    expect(segmentCrossing([0, 0], [10, 0], [0, 1], [10, 1])).toBeUndefined();
  });
});

describe('crossingsOf', () => {
  const street = way('residential', [
    [0, 0],
    [100, 0],
  ]);

  it('marks a footpath crossing the street', () => {
    const crossings = crossingsOf([
      street,
      way('footway', [
        [40, -10],
        [40, 10],
      ]),
    ]);
    expect(crossings).toHaveLength(1);
    expect(crossings[0]!.at).toEqual([40, 0]);
    expect(crossings[0]!.dir).toEqual([1, 0]);
    expect(crossings[0]!.width).toBe(8);
  });

  it('skips paths ending at the kerb, steps and narrow lanes', () => {
    expect(
      crossingsOf([
        street,
        way('footway', [
          [40, 10],
          [40, 3],
        ]),
        way('steps', [
          [60, -10],
          [60, 10],
        ]),
        way(
          'service',
          [
            [0, 50],
            [100, 50],
          ],
          4,
        ),
        way('footway', [
          [50, 40],
          [50, 60],
        ]),
      ]),
    ).toEqual([]);
  });

  it('merges two lines of one crossing', () => {
    const crossings = crossingsOf([
      street,
      way('footway', [
        [40, -10],
        [40, 10],
      ]),
      way('footway', [
        [43, -10],
        [43, 10],
      ]),
    ]);
    expect(crossings).toHaveLength(1);
  });
});

describe('zebraGeometry', () => {
  it('lays bars across the street clear of the kerbs', () => {
    const geometry = zebraGeometry(
      [{ at: [0, 0], dir: [1, 0], width: 8 }],
      0.05,
    )!;
    const position = geometry.getAttribute('position');
    const quads = position.count / 4;
    expect(quads).toBe(7);
    let maxAcross = 0;
    for (let i = 0; i < position.count; i++) {
      // World z is minus north: across the street here.
      maxAcross = Math.max(maxAcross, Math.abs(position.getZ(i)));
      expect(position.getY(i)).toBeCloseTo(0.05);
    }
    expect(maxAcross).toBeLessThanOrEqual(4 - MARKING.zebraMargin + 1e-6);
  });

  it('winds the bars to face up, so the sun lights them', () => {
    const geometry = zebraGeometry(
      [{ at: [0, 0], dir: [0.6, 0.8], width: 8 }],
      0,
    )!;
    const p = geometry.getAttribute('position');
    const [a, b, c] = Array.from(geometry.getIndex()!.array.slice(0, 3)).map(
      (i) => [p.getX(i), p.getY(i), p.getZ(i)] as const,
    );
    const u = [b![0] - a![0], b![2] - a![2]];
    const v = [c![0] - a![0], c![2] - a![2]];
    // y of (b - a) x (c - a), with both vectors flat on the ground.
    expect(u[1]! * v[0]! - u[0]! * v[1]!).toBeGreaterThan(0);
  });

  it('draws nothing without crossings', () => {
    expect(zebraGeometry([], 0)).toBeUndefined();
  });
});

describe('laneLines', () => {
  it('runs down main streets only', () => {
    const lines = laneLines([
      way(
        'primary',
        [
          [0, 0],
          [50, 0],
        ],
        12,
      ),
      way(
        'residential',
        [
          [0, 10],
          [50, 10],
        ],
        9,
      ),
      way(
        'tertiary',
        [
          [0, 20],
          [50, 20],
        ],
        5,
      ),
    ]);
    expect(lines).toHaveLength(1);
    expect(lines[0]!.width).toBe(MARKING.lane.width);
  });
});

describe('pitchLines', () => {
  it('draws touchlines, halfway line and centre circle inside a pitch', () => {
    const lines = pitchLines([
      [0, 0],
      [40, 0],
      [40, 20],
      [0, 20],
      [0, 0],
    ]);
    expect(lines).toHaveLength(3);
    const [outline, halfway, circle] = lines;
    for (const [e, n] of outline!.points) {
      expect(e).toBeGreaterThan(0);
      expect(e).toBeLessThan(40);
      expect(n).toBeGreaterThan(0);
      expect(n).toBeLessThan(20);
    }
    // Across the long side: from the middle of one touchline to the other.
    expect(halfway!.points[0]![0]).toBeCloseTo(20);
    expect(halfway!.points[1]![0]).toBeCloseTo(20);
    const r = Math.hypot(
      circle!.points[0]![0] - 20,
      circle!.points[0]![1] - 10,
    );
    expect(r).toBeCloseTo(4);
  });

  it('leaves odd shapes unmarked', () => {
    expect(
      pitchLines([
        [0, 0],
        [40, 0],
        [30, 20],
        [5, 25],
        [-5, 10],
        [0, 0],
      ]),
    ).toEqual([]);
  });
});
