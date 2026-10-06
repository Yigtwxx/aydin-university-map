import { Uniform } from 'three';

import { enuToWorld } from './coords';
import { openRing } from './geometry';
import type { Building, CampusGraph, Ground } from './types';

/**
 * The opening of the map: the neighbourhood starts as a flat dot-matrix map,
 * the dots lift into the shape of every building, the buildings emerge from
 * the ground under them, a pulse runs through the walking network, then the
 * live map takes over. Everything is driven by one clock (seconds) shared by
 * the points, the massing (facadeMaterial.ts) and the grade (openingGrade.ts).
 */
export const INTRO = {
  /** The dot map fades in. */
  appearS: 0.5,
  /** First building (campus centre) starts to emerge. */
  riseFromS: 0.75,
  /** Time for the emerging wave to reach RISE_RADIUS_M. */
  riseSpanS: 1.45,
  riseRadiusM: 1250,
  /** < 1: the wave lingers on the campus, then sweeps out over the city. */
  risePow: 0.62,
  riseJitterS: 0.16,
  /** One building takes this long to come out of the ground. */
  riseDurS: 0.85,
  /** Dots lift ahead of their building... */
  pointLeadS: 0.7,
  pointRiseS: 0.9,
  /** ...and fade once it has grown into them. */
  pointFadeAfterS: 0.35,
  pointFadeS: 0.55,
  /** The pulse through the walking network. */
  networkFromS: 2.35,
  networkSpanS: 0.75,
  networkHoldS: 0.55,
  /** Scene light: dim at first, the live sky by the end. */
  lightFrom: 0.16,
  lightRiseFromS: 1.0,
  lightRiseToS: 3.15,
  /** The camera starts tilting down into the 3D view. */
  glideS: 0.3,
  /** Panel, controls and labels come in. */
  revealS: 2.95,
  /** The points are gone; the intro unmounts. */
  doneS: 4.3,
} as const;

/** Clock value at which every building stands (no opening, or it is over). */
export const INTRO_OVER = 1e4;

/**
 * The opening's clock, shared as uniforms by the dots (OpeningPoints.tsx), the
 * massing (facadeMaterial.ts) and the grade (openingGrade.ts). One map per page.
 */
export const introClock = {
  /** Seconds since the opening started. */
  time: new Uniform(INTRO_OVER),
  /** Scene light: INTRO.lightFrom .. 1. */
  light: new Uniform(1),
};

/** Sets the clock up for a scene that plays the opening or skips it. */
export function resetIntroClock(playing: boolean): void {
  introClock.time.value = playing ? 0 : INTRO_OVER;
  introClock.light.value = playing ? INTRO.lightFrom : 1;
}

export type PointKind = 'campus' | 'city' | 'ground' | 'network';
const KIND_INDEX: Record<PointKind, number> = {
  campus: 0,
  city: 1,
  ground: 2,
  network: 3,
};

/** Linear RGB of each kind (the points are drawn unlit and additive). */
const KIND_COLOR: Record<PointKind, [number, number, number]> = {
  campus: [1.0, 0.72, 0.32],
  city: [0.5, 0.66, 0.92],
  ground: [0.3, 0.38, 0.52],
  network: [0.08, 0.36, 1.0],
};

/** Longer entrance links cross the building between two doors. */
const MAX_ENTRANCE_LINK_M = 40;

/** Grid of the flat dot map the points start from (m). */
const GRID_M: Record<'campus' | 'city', number> = { campus: 2.2, city: 3.6 };
/** Dots sit just off walls and roofs so they never z-fight the massing. */
const SURFACE_OFFSET_M = 0.3;

export function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/** Scene light (INTRO.lightFrom .. 1) at intro time `t`. */
export function introLight(t: number): number {
  const k = smoothstep(INTRO.lightRiseFromS, INTRO.lightRiseToS, t);
  return INTRO.lightFrom + (1 - INTRO.lightFrom) * k;
}

/** Centre of the campus buildings (ENU), where the wave starts. */
export function introOrigin(buildings: Building[]): [number, number] {
  let e = 0;
  let n = 0;
  let count = 0;
  for (const b of buildings) {
    if (!b.campus) continue;
    const [ce, cn] = centroid(b.outline);
    e += ce;
    n += cn;
    count++;
  }
  return count ? [e / count, n / count] : [0, 0];
}

/** When the building at `distance` m from the origin starts to emerge (s). */
export function riseStart(distanceM: number, seed: number): number {
  const share = Math.min(1, Math.max(0, distanceM / INTRO.riseRadiusM));
  return (
    INTRO.riseFromS +
    INTRO.riseSpanS * share ** INTRO.risePow +
    seed * INTRO.riseJitterS
  );
}

export function centroid(outline: [number, number][]): [number, number] {
  const ring = openRing(outline);
  let e = 0;
  let n = 0;
  for (const [x, y] of ring) {
    e += x;
    n += y;
  }
  return ring.length ? [e / ring.length, n / ring.length] : [0, 0];
}

export interface IntroPoints {
  count: number;
  /** World positions the dots settle on (xyz). */
  position: Float32Array;
  /** World positions on the flat dot map (xyz). */
  start: Float32Array;
  /** (lift start s, fade start s, kind index, per-point seed 0..1). */
  timing: Float32Array;
  color: Float32Array;
}

interface SampleOptions {
  /** Total number of points (the device decides: fewer on phones). */
  budget: number;
  /** Building seeds, as the massing uses them (massing.seedOf). */
  seedOf: (id: string) => number;
}

/** Deterministic PRNG (mulberry32), so the opening looks the same each time. */
function random(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

class PointSink {
  private position: number[] = [];
  private start: number[] = [];
  private timing: number[] = [];
  private color: number[] = [];

  constructor(private readonly rand: () => number) {}

  add(
    kind: PointKind,
    world: [number, number, number],
    from: [number, number, number],
    lift: number,
    fade: number,
  ) {
    this.position.push(...world);
    this.start.push(...from);
    this.timing.push(lift, fade, KIND_INDEX[kind], this.rand());
    this.color.push(...KIND_COLOR[kind]);
  }

  build(): IntroPoints {
    return {
      count: this.position.length / 3,
      position: new Float32Array(this.position),
      start: new Float32Array(this.start),
      timing: new Float32Array(this.timing),
      color: new Float32Array(this.color),
    };
  }
}

/** Where a dot starts: its spot snapped to the flat dot-matrix grid. */
function flat(e: number, n: number, grid: number): [number, number, number] {
  return enuToWorld(
    Math.round(e / grid) * grid,
    Math.round(n / grid) * grid,
    0.35,
  );
}

interface Shape {
  b: Building;
  ring: [number, number][];
  perimeter: number;
  area: number;
  corners: number[];
  /** +1 for counter-clockwise rings, -1 for clockwise (outward normals). */
  sign: number;
  weight: number;
  distance: number;
}

function shapeOf(b: Building, origin: [number, number]): Shape | undefined {
  const ring = openRing(b.outline);
  if (ring.length < 3) return undefined;
  let perimeter = 0;
  let area = 0;
  const corners: number[] = [];
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!;
    const c = ring[(i + 1) % ring.length]!;
    const p = ring[(i + ring.length - 1) % ring.length]!;
    perimeter += Math.hypot(c[0] - a[0], c[1] - a[1]);
    area += a[0] * c[1] - c[0] * a[1];
    const turn = Math.abs(
      Math.atan2(c[1] - a[1], c[0] - a[0]) -
        Math.atan2(a[1] - p[1], a[0] - p[0]),
    );
    const bend = Math.min(turn, 2 * Math.PI - turn);
    if (bend > 0.5) corners.push(i);
  }
  const sign = area >= 0 ? 1 : -1;
  area = Math.abs(area) / 2;
  const [ce, cn] = centroid(b.outline);
  const distance = Math.hypot(ce - origin[0], cn - origin[1]);
  const height = b.height_m;
  // Outlines carry the shape; walls and roofs only a light fill.
  const weight = b.campus
    ? (perimeter * (1 + height * 0.08) + area * 0.012) * 6
    : perimeter * (1 + height * 0.04) + area * 0.004;
  return { b, ring, perimeter, area, corners, sign, weight, distance };
}

/** Point on the ring at arc length `s`, with the outward normal there. */
function along(
  ring: [number, number][],
  sign: number,
  s: number,
): { p: [number, number]; normal: [number, number] } {
  let left = s;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!;
    const c = ring[(i + 1) % ring.length]!;
    const len = Math.hypot(c[0] - a[0], c[1] - a[1]);
    if (left <= len || i === ring.length - 1) {
      const k = len > 0 ? Math.min(1, left / len) : 0;
      const dx = len > 0 ? (c[0] - a[0]) / len : 0;
      const dy = len > 0 ? (c[1] - a[1]) / len : 0;
      // Counter-clockwise rings: outward is to the right of a -> c.
      return {
        p: [a[0] + (c[0] - a[0]) * k, a[1] + (c[1] - a[1]) * k],
        normal: [dy * sign, -dx * sign],
      };
    }
    left -= len;
  }
  return { p: ring[0]!, normal: [0, 0] };
}

function insideRing(p: [number, number], ring: [number, number][]): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if (
      yi > p[1] !== yj > p[1] &&
      p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi
    )
      hit = !hit;
  }
  return hit;
}

/** Spreads `count` points over the building: roof outline, corners, walls, roof. */
function sampleBuilding(
  sink: PointSink,
  shape: Shape,
  count: number,
  seed: number,
  rand: () => number,
) {
  const { b, ring, perimeter, corners, sign } = shape;
  const kind: PointKind = b.campus ? 'campus' : 'city';
  const grid = GRID_M[b.campus ? 'campus' : 'city'];
  const top = b.height_m + SURFACE_OFFSET_M * 0.5;
  const rise = riseStart(shape.distance, seed);
  const lift = rise - INTRO.pointLeadS;
  const fade = rise + INTRO.pointFadeAfterS;
  const jitter = () => (rand() - 0.5) * 0.16;
  const emit = (e: number, n: number, up: number) =>
    sink.add(
      kind,
      enuToWorld(e, n, up),
      flat(e, n, grid),
      lift + jitter(),
      fade + jitter(),
    );

  // The campus gets a full shell; the city mostly its outlines, which read
  // as buildings from far away where a fill reads as noise.
  const share = b.campus
    ? { edge: 0.42, vertical: 0.18, wall: 0.28 }
    : { edge: 0.62, vertical: 0.26, wall: 0.08 };
  const edge = Math.max(3, Math.round(count * share.edge));
  const vertical = corners.length ? Math.round(count * share.vertical) : 0;
  const wall = Math.round(count * share.wall);
  const roof = Math.max(0, count - edge - vertical - wall);

  // Roof outline, evenly spaced: the crisp silhouette.
  for (let i = 0; i < edge; i++) {
    const { p, normal } = along(
      ring,
      sign,
      (perimeter * (i + rand() * 0.3)) / edge,
    );
    emit(
      p[0] + normal[0] * SURFACE_OFFSET_M,
      p[1] + normal[1] * SURFACE_OFFSET_M,
      top,
    );
  }
  // Vertical corner edges.
  const perCorner = corners.length ? Math.max(2, vertical / corners.length) : 0;
  for (const index of corners) {
    const [e, n] = ring[index]!;
    for (let k = 0; k < perCorner; k++)
      emit(e, n, (top * (k + 0.5)) / perCorner);
  }
  // A light fill over the walls.
  for (let i = 0; i < wall; i++) {
    const { p, normal } = along(ring, sign, rand() * perimeter);
    emit(
      p[0] + normal[0] * SURFACE_OFFSET_M,
      p[1] + normal[1] * SURFACE_OFFSET_M,
      rand() * top,
    );
  }
  // And over the roof.
  if (roof > 0) {
    let minE = Infinity;
    let minN = Infinity;
    let maxE = -Infinity;
    let maxN = -Infinity;
    for (const [e, n] of ring) {
      minE = Math.min(minE, e);
      maxE = Math.max(maxE, e);
      minN = Math.min(minN, n);
      maxN = Math.max(maxN, n);
    }
    for (let i = 0, tries = 0; i < roof && tries < roof * 6; tries++) {
      const p: [number, number] = [
        minE + rand() * (maxE - minE),
        minN + rand() * (maxN - minN),
      ];
      if (!insideRing(p, ring)) continue;
      emit(p[0], p[1], top);
      i++;
    }
  }
}

/** Visits evenly spaced points along a polyline (ENU). */
function alongLine(
  line: [number, number][],
  spacing: number,
  visit: (e: number, n: number, s: number) => void,
) {
  let carried = 0;
  let travelled = 0;
  for (let i = 0; i + 1 < line.length; i++) {
    const a = line[i]!;
    const c = line[i + 1]!;
    const len = Math.hypot(c[0] - a[0], c[1] - a[1]);
    let s = carried;
    while (s < len) {
      const k = s / len;
      visit(a[0] + (c[0] - a[0]) * k, a[1] + (c[1] - a[1]) * k, travelled + s);
      s += spacing;
    }
    carried = s - len;
    travelled += len;
  }
}

function lineLength(line: [number, number][]): number {
  let total = 0;
  for (let i = 0; i + 1 < line.length; i++)
    total += Math.hypot(
      line[i + 1]![0] - line[i]![0],
      line[i + 1]![1] - line[i]![1],
    );
  return total;
}

/**
 * The dots of the opening: building outlines and surfaces (the campus four
 * times as dense), streets and paths on the ground, and the walking network,
 * which lights up last. Deterministic for the same data.
 */
export function sampleIntroPoints(
  buildings: Building[],
  ground: Ground | undefined,
  graph: CampusGraph,
  { budget, seedOf }: SampleOptions,
): IntroPoints {
  const rand = random(0x5eed);
  const sink = new PointSink(rand);
  const origin = introOrigin(buildings);
  const networkBudget = Math.round(budget * 0.04);
  const groundBudget = Math.round(budget * 0.12);
  const buildingBudget = budget - networkBudget - groundBudget;

  const shapes = buildings
    .map((b) => shapeOf(b, origin))
    .filter((s): s is Shape => !!s);
  const totalWeight = shapes.reduce((sum, s) => sum + s.weight, 0);
  for (const shape of shapes) {
    const exact = (shape.weight / totalWeight) * buildingBudget;
    const count = Math.floor(exact) + (rand() < exact % 1 ? 1 : 0);
    if (count > 0) sampleBuilding(sink, shape, count, seedOf(shape.b.id), rand);
  }

  if (ground) {
    const ways = ground.ways.filter((w) => w.line.length > 1);
    const total = ways.reduce((sum, w) => sum + lineLength(w.line), 0);
    const spacing = Math.max(1.5, total / Math.max(1, groundBudget));
    for (const way of ways) {
      alongLine(way.line, spacing, (e, n) => {
        const fade =
          riseStart(Math.hypot(e - origin[0], n - origin[1]), 0.5) +
          INTRO.pointFadeAfterS;
        const at = enuToWorld(e, n, 0.25);
        sink.add('ground', at, at, 0, fade);
      });
    }
  }

  const lines = graph.edges.flatMap((edge) => {
    const a = graph.byId.get(edge.source);
    const c = graph.byId.get(edge.target);
    if (!a || !c || a.kind === 'indoor' || c.kind === 'indoor') return [];
    // The paths walked in the tour, outside: line-of-sight links fill the
    // plazas with a mesh, and long entrance links run through the building.
    if (edge.origin === 'inferred') return [];
    const outside =
      edge.kind === 'outdoor' ||
      (edge.kind === 'entrance' && edge.length_m <= MAX_ENTRANCE_LINK_M);
    if (!outside) return [];
    const line: [number, number][] = edge.path_enu?.length
      ? edge.path_enu
      : [
          [a.enu[0], a.enu[1]],
          [c.enu[0], c.enu[1]],
        ];
    return [line];
  });
  const networkLength = lines.reduce((sum, l) => sum + lineLength(l), 0);
  const spacing = Math.max(2.2, networkLength / Math.max(1, networkBudget));
  // Edges overlap where paths meet: one dot per cell keeps the pulse crisp.
  const taken = new Set<string>();
  let reach = 1;
  for (const node of graph.nodes)
    reach = Math.max(
      reach,
      Math.hypot(node.enu[0] - origin[0], node.enu[1] - origin[1]),
    );
  for (const line of lines) {
    alongLine(line, spacing, (e, n) => {
      const cell = `${Math.round(e / 1.8)},${Math.round(n / 1.8)}`;
      if (taken.has(cell)) return;
      taken.add(cell);
      const d = Math.hypot(e - origin[0], n - origin[1]);
      const pulse =
        INTRO.networkFromS + INTRO.networkSpanS * (d / reach) ** 0.8;
      const at = enuToWorld(e, n, 0.45);
      sink.add('network', at, at, pulse, pulse + INTRO.networkHoldS);
    });
  }
  return sink.build();
}
