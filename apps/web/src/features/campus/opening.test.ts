import { describe, expect, it } from 'vitest';

import { seedOf } from './massing';
import {
  INTRO,
  introLight,
  introOrigin,
  riseStart,
  sampleIntroPoints,
} from './opening';
import type { Building, CampusGraph, GraphEdge, GraphNode } from './types';

const square = (e: number, n: number, size: number): [number, number][] => [
  [e, n],
  [e + size, n],
  [e + size, n + size],
  [e, n + size],
  [e, n],
];

const building = (
  id: string,
  e: number,
  n: number,
  campus: boolean,
): Building => ({
  id,
  name: null,
  campus,
  height_m: 12,
  outline: square(e, n, 20),
});

const node = (
  id: string,
  e: number,
  n: number,
  kind: GraphNode['kind'] = 'outdoor',
): GraphNode => ({
  id,
  kind,
  lat: 0,
  lng: 0,
  alt_m: 0,
  enu: [e, n, 0],
  heading_deg: 0,
  label: { tr: id, en: id },
  area: { tr: '', en: '' },
  building: null,
});

function graphOf(nodes: GraphNode[], edges: GraphEdge[]): CampusGraph {
  return {
    nodes,
    edges,
    byId: new Map(nodes.map((n) => [n.id, n])),
    edgeById: new Map(edges.map((e) => [e.id, e])),
  };
}

const edge = (
  source: string,
  target: string,
  extra: Partial<GraphEdge> = {},
): GraphEdge => ({
  id: `${source}|${target}`,
  source,
  target,
  kind: 'outdoor',
  length_m: 60,
  ...extra,
});

const BUILDINGS = [
  building('way/1', 0, 0, true),
  building('way/2', 300, 0, false),
  building('way/3', 0, 600, false),
];
const GRAPH = graphOf(
  [node('a', 0, -10), node('b', 60, -10), node('c', 0, 40, 'indoor')],
  [
    edge('a', 'b', { origin: 'tour' }),
    edge('a', 'c', { kind: 'indoor', origin: 'tour' }),
  ],
);

describe('opening timeline', () => {
  it('raises the campus first and the far city last', () => {
    expect(riseStart(0, 0)).toBe(INTRO.riseFromS);
    expect(riseStart(200, 0)).toBeLessThan(riseStart(800, 0));
    expect(riseStart(INTRO.riseRadiusM * 4, 0)).toBeCloseTo(
      INTRO.riseFromS + INTRO.riseSpanS,
    );
  });

  it('finishes every building and dot before the opening unmounts', () => {
    const lastRise = riseStart(INTRO.riseRadiusM, 1);
    expect(lastRise + INTRO.riseDurS).toBeLessThan(INTRO.doneS);
    const lastDot = lastRise + INTRO.pointFadeAfterS + 0.08 + INTRO.pointFadeS;
    expect(lastDot).toBeLessThan(INTRO.doneS);
    const lastPulse =
      INTRO.networkFromS +
      INTRO.networkSpanS +
      INTRO.networkHoldS +
      INTRO.pointFadeS;
    expect(lastPulse).toBeLessThanOrEqual(INTRO.doneS);
  });

  it('brings the light from dim to the live sky', () => {
    expect(introLight(0)).toBeCloseTo(INTRO.lightFrom);
    expect(introLight(INTRO.lightRiseToS)).toBe(1);
    expect(introLight(2)).toBeGreaterThan(introLight(1.5));
  });

  it('starts the wave at the centre of the campus buildings', () => {
    expect(introOrigin(BUILDINGS)).toEqual([10, 10]);
  });
});

describe('sampleIntroPoints', () => {
  const sample = (budget = 4000) =>
    sampleIntroPoints(BUILDINGS, undefined, GRAPH, { budget, seedOf });

  it('stays near the budget with matching attribute sizes', () => {
    const points = sample();
    expect(points.count).toBeGreaterThan(3000);
    expect(points.count).toBeLessThan(4400);
    expect(points.position.length).toBe(points.count * 3);
    expect(points.start.length).toBe(points.count * 3);
    expect(points.timing.length).toBe(points.count * 4);
    expect(points.color.length).toBe(points.count * 3);
  });

  it('gives the campus more dots than a city building of the same size', () => {
    const points = sample();
    let campus = 0;
    let city = 0;
    for (let i = 0; i < points.count; i++) {
      const kind = points.timing[i * 4 + 2];
      if (kind === 0) campus++;
      if (kind === 1) city++;
    }
    // Two city buildings against one campus building.
    expect(campus).toBeGreaterThan(city);
  });

  it('starts building dots on the flat map and lands them on the building', () => {
    const points = sample();
    for (let i = 0; i < points.count; i++) {
      if (points.timing[i * 4 + 2]! > 1) continue;
      expect(points.start[i * 3 + 1]).toBeCloseTo(0.35);
      expect(points.position[i * 3 + 1]).toBeGreaterThanOrEqual(0);
      expect(points.position[i * 3 + 1]).toBeLessThanOrEqual(12.5);
    }
  });

  it('pulses only the outdoor tour paths', () => {
    const points = sample();
    for (let i = 0; i < points.count; i++) {
      if (points.timing[i * 4 + 2] !== 3) continue;
      // World z is -north: the a-b path runs along north = -10.
      expect(points.position[i * 3 + 2]).toBeCloseTo(10);
    }
  });

  it('is deterministic', () => {
    expect(sample().position).toEqual(sample().position);
  });
});
