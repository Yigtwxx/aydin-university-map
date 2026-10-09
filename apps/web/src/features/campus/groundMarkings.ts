import { BufferGeometry, Float32BufferAttribute } from 'three';

import { enuToWorld } from './coords';
import { openRing } from './geometry';
import { lineLength, type RibbonLine } from './ribbon';
import type { Ground } from './types';

type XY = [number, number];

export type RoadClass = 'major' | 'minor' | 'path';

const MAJOR = new Set([
  'motorway',
  'motorway_link',
  'trunk',
  'trunk_link',
  'primary',
  'primary_link',
  'secondary',
  'secondary_link',
  'busway',
]);
const PATH = new Set([
  'footway',
  'path',
  'pedestrian',
  'steps',
  'cycleway',
  'bridleway',
  'track',
]);

export function roadClass(kind: string): RoadClass {
  if (MAJOR.has(kind)) return 'major';
  if (PATH.has(kind)) return 'path';
  return 'minor';
}

/** Footpaths that cross a street at a zebra (not steps or tracks). */
const WALKS = new Set(['footway', 'path', 'pedestrian']);
/** Streets wide enough to carry a painted crossing or a lane line. */
const CROSSING_MIN_WIDTH_M = 6;
/** Through roads with a painted centre line (slip roads and bus lanes have none). */
const LANE_LINE_KINDS = new Set([
  'motorway',
  'trunk',
  'primary',
  'secondary',
  'tertiary',
]);
/** Shorter ways are junction stubs, where a line would only clutter. */
const LANE_LINE_MIN_M = 40;

/** Painted marking sizes, metres. */
export const MARKING = {
  /** Dashed lane line: width, dash and gap. */
  lane: { width: 0.18, dash: 3, gap: 5 },
  /** Zebra: bar length along the street, bar width, spacing across it. */
  zebra: { length: 3, bar: 0.5, pitch: 1 },
  /** Kerbside margin the zebra keeps clear on each side. */
  zebraMargin: 0.4,
  /** Pitch lines and the margin they keep inside the pitch's edge. */
  pitch: { width: 0.22, inset: 1.2, circle: 9.15 },
  /** Two crossings of one street closer than this are the same crossing. */
  crossingMerge: 8,
} as const;

/** Where a footpath crosses a street: point, street direction and width. */
export interface Crossing {
  at: XY;
  /** Unit direction of the street there. */
  dir: XY;
  width: number;
}

/** Crossing point of segments ab and cd strictly inside both, else undefined. */
export function segmentCrossing(a: XY, b: XY, c: XY, d: XY): XY | undefined {
  const rx = b[0] - a[0];
  const ry = b[1] - a[1];
  const sx = d[0] - c[0];
  const sy = d[1] - c[1];
  const denom = rx * sy - ry * sx;
  if (Math.abs(denom) < 1e-9) return undefined;
  const qx = c[0] - a[0];
  const qy = c[1] - a[1];
  const t = (qx * sy - qy * sx) / denom;
  const u = (qx * ry - qy * rx) / denom;
  const eps = 1e-6;
  if (t <= eps || t >= 1 - eps || u <= eps || u >= 1 - eps) return undefined;
  return [a[0] + rx * t, a[1] + ry * t];
}

type Box = [number, number, number, number];

function boxOf(line: XY[]): Box {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const [x, y] of line) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}

const overlaps = (a: Box, b: Box) =>
  a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];

/**
 * The zebra crossings: every place a footpath crosses a street wide enough
 * to paint one (a path ending at the kerb does not cross it). Crossings of
 * one street a few metres apart (a path drawn as two lines) merge.
 */
export function crossingsOf(ways: Ground['ways']): Crossing[] {
  const streets = ways
    .filter(
      (w) => roadClass(w.kind) !== 'path' && w.width_m >= CROSSING_MIN_WIDTH_M,
    )
    .map((w) => ({ line: w.line, width: w.width_m, box: boxOf(w.line) }));
  const walks = ways
    .filter((w) => WALKS.has(w.kind))
    .map((w) => ({ line: w.line, box: boxOf(w.line) }));
  const out: Crossing[] = [];
  for (const street of streets) {
    const found: Crossing[] = [];
    for (const walk of walks) {
      if (!overlaps(street.box, walk.box)) continue;
      for (let i = 1; i < street.line.length; i++) {
        const a = street.line[i - 1]!;
        const b = street.line[i]!;
        for (let j = 1; j < walk.line.length; j++) {
          const at = segmentCrossing(a, b, walk.line[j - 1]!, walk.line[j]!);
          if (!at) continue;
          if (
            found.some(
              (c) =>
                Math.hypot(c.at[0] - at[0], c.at[1] - at[1]) <
                MARKING.crossingMerge,
            )
          )
            continue;
          const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
          found.push({
            at,
            dir: [(b[0] - a[0]) / len, (b[1] - a[1]) / len],
            width: street.width,
          });
        }
      }
    }
    out.push(...found);
  }
  return out;
}

/**
 * Zebra bars as flat quads at `height`: bars run along the street, side by
 * side across it, clear of the kerbs.
 */
export function zebraGeometry(
  crossings: readonly Crossing[],
  height: number,
): BufferGeometry | undefined {
  const { length, bar, pitch } = MARKING.zebra;
  const positions: number[] = [];
  const indices: number[] = [];
  for (const { at, dir, width } of crossings) {
    const across: XY = [-dir[1], dir[0]];
    const span = width - 2 * MARKING.zebraMargin;
    const bars = Math.max(1, Math.floor((span - bar) / pitch) + 1);
    const first = -((bars - 1) * pitch) / 2;
    for (let k = 0; k < bars; k++) {
      const o = first + k * pitch;
      const corner = (s: number, t: number) =>
        enuToWorld(
          at[0] + dir[0] * s + across[0] * (o + t),
          at[1] + dir[1] * s + across[1] * (o + t),
          height,
        );
      const base = positions.length / 3;
      positions.push(
        ...corner(-length / 2, -bar / 2),
        ...corner(length / 2, -bar / 2),
        ...corner(length / 2, bar / 2),
        ...corner(-length / 2, bar / 2),
      );
      // Counter-clockwise seen from above (world y up, z south).
      indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
  }
  if (indices.length === 0) return undefined;
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  geometry.setAttribute(
    'normal',
    new Float32BufferAttribute(
      positions.map((_, i) => (i % 3 === 1 ? 1 : 0)),
      3,
    ),
  );
  geometry.setIndex(indices);
  return geometry;
}

/** Lane lines down the middle of the main streets (dashed when drawn). */
export function laneLines(ways: Ground['ways']): RibbonLine[] {
  return ways
    .filter(
      (w) =>
        LANE_LINE_KINDS.has(w.kind) &&
        w.width_m >= 7 &&
        lineLength(w.line) >= LANE_LINE_MIN_M,
    )
    .map((w) => ({ points: w.line, width: MARKING.lane.width }));
}

/**
 * The white lines of a rectangular pitch (an outline of four corners):
 * touchlines inset from the edge, the halfway line across the long side and
 * the centre circle. Other shapes (a pool hall's grounds) get none.
 */
export function pitchLines(outline: XY[]): RibbonLine[] {
  const ring = openRing(outline);
  if (ring.length !== 4) return [];
  const [a, b, c, d] = ring as [XY, XY, XY, XY];
  const ab = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const bc = Math.hypot(c[0] - b[0], c[1] - b[1]);
  const cd = Math.hypot(d[0] - c[0], d[1] - c[1]);
  const da = Math.hypot(a[0] - d[0], a[1] - d[1]);
  // Roughly a rectangle: opposite sides agree.
  if (Math.abs(ab - cd) > 0.15 * Math.max(ab, cd)) return [];
  if (Math.abs(bc - da) > 0.15 * Math.max(bc, da)) return [];
  const { width, inset, circle } = MARKING.pitch;
  const short = Math.min(ab, bc);
  if (short < 4 * inset) return [];
  const centre: XY = [
    (a[0] + b[0] + c[0] + d[0]) / 4,
    (a[1] + b[1] + c[1] + d[1]) / 4,
  ];
  // Pull each corner towards the centre so the lines keep inside the grass.
  const shrink = (p: XY): XY => {
    const dx = centre[0] - p[0];
    const dy = centre[1] - p[1];
    const len = Math.hypot(dx, dy);
    const k = (inset * Math.SQRT2) / len;
    return [p[0] + dx * k, p[1] + dy * k];
  };
  const [ia, ib, ic, id] = [shrink(a), shrink(b), shrink(c), shrink(d)];
  const mid = (p: XY, q: XY): XY => [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
  // The halfway line joins the midpoints of the long sides.
  const halfway: XY[] =
    ab >= bc ? [mid(ia, ib), mid(ic, id)] : [mid(ib, ic), mid(id, ia)];
  const radius = Math.min(circle, short / 5);
  const ringPts: XY[] = [];
  for (let k = 0; k <= 32; k++) {
    const t = (k / 32) * Math.PI * 2;
    ringPts.push([
      centre[0] + Math.cos(t) * radius,
      centre[1] + Math.sin(t) * radius,
    ]);
  }
  return [
    { points: [ia, ib, ic, id, ia], width },
    { points: halfway, width },
    { points: ringPts, width },
  ];
}
