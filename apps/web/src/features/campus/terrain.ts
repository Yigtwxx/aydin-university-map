import { ShapeUtils, Vector2 } from 'three';

import type {
  Furniture,
  Ramp,
  Stairs,
  Terrace,
  TerraceEdge,
} from './furniture';
import { openRing } from './geometry';

type XY = [number, number];

/** Width of a grassy bank per metre it climbs (about 29°), clamped. */
const BANK_RUN_PER_M = 1.8;
const BANK_MIN_M = 0.6;
const BANK_MAX_M = 8;

/** A straight flight of stairs or a ramp, in its own frame. */
export interface Flight {
  id: string;
  kind: 'stairs' | 'ramp';
  foot: XY;
  top: XY;
  /** Unit vector from the foot to the top. */
  dir: XY;
  /** Unit vector to the left, walking up. */
  left: XY;
  run: number;
  width: number;
  base: number;
  rise: number;
  /**
   * The drawn outline when it is not the rectangle round the walking line
   * (tiers fanned to meet their neighbours); left as seen walking up.
   */
  corners?: FlightCorners;
}

export interface FlightCorners {
  footLeft: XY;
  footRight: XY;
  topLeft: XY;
  topRight: XY;
}

/** A terrace ready to draw and to answer heights. */
export interface TerraceShape {
  id: string;
  /** Open ring, counter-clockwise seen from above (ENU metres). */
  ring: XY[];
  /** Rings of the terraces standing inside this one, cut out of its top. */
  holes: XY[][];
  z: number;
  /** Height of the ground around it: the terrace it stands in, or 0. */
  surround: number;
  /** Index of the terrace it stands in, or -1 for the street datum. */
  parent: number;
  edge: TerraceEdge;
  area: number;
  /** [minEast, minNorth, maxEast, maxNorth]. */
  bbox: [number, number, number, number];
  /** Top surface triangles (holes cut), ENU [e, n] × 3 per triangle. */
  triangles: number[];
  /** How far a 'slope' edge's bank reaches out from the ring (m), else 0. */
  bank: number;
}

/**
 * Ground height over the campus: the street datum (0) everywhere except on
 * terraces (their level), on their grassy banks (falling away), and on
 * stairs and ramps (interpolated along the flight).
 */
export interface Terrain {
  /** True when the ground is flat everywhere (no terraces, no flights). */
  readonly flat: boolean;
  readonly terraces: readonly TerraceShape[];
  readonly flights: readonly Flight[];
  heightAt(east: number, north: number): number;
}

export const FLAT_TERRAIN: Terrain = {
  flat: true,
  terraces: [],
  flights: [],
  heightAt: () => 0,
};

export function signedArea(ring: XY[]): number {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const [ax, ay] = ring[i]!;
    const [bx, by] = ring[(i + 1) % ring.length]!;
    sum += ax * by - bx * ay;
  }
  return sum / 2;
}

/** Even-odd point in polygon (open ring). */
export function pointInRing(e: number, n: number, ring: XY[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if (yi > n !== yj > n && e < ((xj - xi) * (n - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}

/** Distance from a point to a ring's boundary. */
export function distanceToRing(e: number, n: number, ring: XY[]): number {
  let best = Infinity;
  for (let i = 0; i < ring.length; i++) {
    const [ax, ay] = ring[i]!;
    const [bx, by] = ring[(i + 1) % ring.length]!;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t =
      len2 === 0
        ? 0
        : Math.max(0, Math.min(1, ((e - ax) * dx + (n - ay) * dy) / len2));
    best = Math.min(best, Math.hypot(e - (ax + t * dx), n - (ay + t * dy)));
  }
  return best;
}

export function flightOf(f: Stairs | Ramp, kind: Flight['kind']): Flight {
  const dx = f.top[0] - f.foot[0];
  const dy = f.top[1] - f.foot[1];
  const run = Math.hypot(dx, dy) || 1;
  const dir: XY = [dx / run, dy / run];
  const c = 'corners' in f ? f.corners : null;
  return {
    id: f.id,
    kind,
    foot: f.foot,
    top: f.top,
    dir,
    left: [-dir[1], dir[0]],
    run,
    width: f.width_m,
    base: f.base_z,
    rise: f.rise_m,
    ...(c && {
      corners: {
        footLeft: c.foot_left,
        footRight: c.foot_right,
        topLeft: c.top_left,
        topRight: c.top_right,
      },
    }),
  };
}

/** A flight's outline: its corners, or the rectangle round its line. */
export function flightCorners(f: Flight): FlightCorners {
  if (f.corners) return f.corners;
  const h = f.width / 2;
  const at = (p: XY, side: number): XY => [
    p[0] + f.left[0] * h * side,
    p[1] + f.left[1] * h * side,
  ];
  return {
    footLeft: at(f.foot, 1),
    footRight: at(f.foot, -1),
    topLeft: at(f.top, 1),
    topRight: at(f.top, -1),
  };
}

/** Distance from a point to the line through a and b. */
function lineDistance(e: number, n: number, a: XY, b: XY): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  return (
    Math.abs(dx * (n - a[1]) - dy * (e - a[0])) / (Math.hypot(dx, dy) || 1)
  );
}

/**
 * How far up a flight a point is (0 at the foot, 1 at the top), or
 * undefined off it. A fanned flight's foot and top edges need not be
 * parallel: the share runs between the two.
 */
export function flightShare(
  f: Flight,
  e: number,
  n: number,
): number | undefined {
  if (!f.corners) {
    const [along, across] = flightCoords(f, e, n);
    return along >= 0 && along <= f.run && Math.abs(across) <= f.width / 2
      ? along / f.run
      : undefined;
  }
  const c = f.corners;
  const quad = [c.footRight, c.topRight, c.topLeft, c.footLeft];
  // Its edges count, as a rectangle's do.
  if (!pointInRing(e, n, quad) && distanceToRing(e, n, quad) > 1e-6)
    return undefined;
  const toFoot = lineDistance(e, n, c.footLeft, c.footRight);
  const toTop = lineDistance(e, n, c.topLeft, c.topRight);
  return toFoot / (toFoot + toTop || 1);
}

/** Position in a flight's frame: metres along from the foot, and to the left. */
export function flightCoords(f: Flight, e: number, n: number): XY {
  const de = e - f.foot[0];
  const dn = n - f.foot[1];
  return [de * f.dir[0] + dn * f.dir[1], de * f.left[0] + dn * f.left[1]];
}

function bboxOf(ring: XY[]): [number, number, number, number] {
  let minE = Infinity;
  let minN = Infinity;
  let maxE = -Infinity;
  let maxN = -Infinity;
  for (const [e, n] of ring) {
    minE = Math.min(minE, e);
    minN = Math.min(minN, n);
    maxE = Math.max(maxE, e);
    maxN = Math.max(maxN, n);
  }
  return [minE, minN, maxE, maxN];
}

const inBox = (
  e: number,
  n: number,
  [minE, minN, maxE, maxN]: [number, number, number, number],
  pad = 0,
) => e >= minE - pad && e <= maxE + pad && n >= minN - pad && n <= maxN + pad;

/** Triangles of a ring with holes, as ENU [e, n] × 3 each. */
function triangulate(ring: XY[], holes: XY[][]): number[] {
  const contour = ring.map(([e, n]) => new Vector2(e, n));
  const holeVectors = holes.map((h) => h.map(([e, n]) => new Vector2(e, n)));
  const all = [...contour, ...holeVectors.flat()];
  const out: number[] = [];
  for (const [a, b, c] of ShapeUtils.triangulateShape(contour, holeVectors)) {
    for (const index of [a, b, c]) {
      const v = all[index!]!;
      out.push(v.x, v.y);
    }
  }
  return out;
}

/**
 * How far a terrace's bank reaches out from its outline: the terrace's own
 * `bank_m` when given (where buildings or a street leave less room), else
 * sized from the climb. Only 'slope' edges that climb have one.
 */
export function bankWidth(
  terrace: Pick<Terrace, 'edge' | 'bank_m'>,
  climb: number,
): number {
  if (terrace.edge !== 'slope' || climb <= 0) return 0;
  if (terrace.bank_m != null && terrace.bank_m > 0) return terrace.bank_m;
  return Math.min(BANK_MAX_M, Math.max(BANK_MIN_M, climb * BANK_RUN_PER_M));
}

/** Builds the terrain of a furniture collection. */
export function createTerrain(furniture: Furniture): Terrain {
  const flights = [
    ...furniture.stairs.map((s) => flightOf(s, 'stairs')),
    ...furniture.ramps.map((r) => flightOf(r, 'ramp')),
  ];
  const raw = furniture.terraces
    .map((t) => {
      let ring = openRing(t.outline);
      if (signedArea(ring) < 0) ring = [...ring].reverse();
      return { source: t, ring, area: signedArea(ring), bbox: bboxOf(ring) };
    })
    .filter((t) => t.ring.length >= 3 && t.area > 1e-6);

  // A terrace stands in the smallest terrace that holds all its corners.
  const parents = raw.map((t, i) => {
    let best = -1;
    for (let j = 0; j < raw.length; j++) {
      const other = raw[j]!;
      if (j === i || other.area <= t.area) continue;
      if (!t.ring.every(([e, n]) => pointInRing(e, n, other.ring))) continue;
      if (best < 0 || other.area < raw[best]!.area) best = j;
    }
    return best;
  });
  const terraces: TerraceShape[] = raw.map((t, i) => {
    const parent = parents[i]!;
    const surround = parent >= 0 ? raw[parent]!.source.z_m : 0;
    const holes = raw
      .filter((_, j) => parents[j] === i)
      .map((child) => [...child.ring].reverse());
    const climb = Math.abs(t.source.z_m - surround);
    return {
      id: t.source.id,
      ring: t.ring,
      holes,
      z: t.source.z_m,
      surround,
      parent,
      edge: t.source.edge,
      area: t.area,
      bbox: t.bbox,
      triangles: triangulate(t.ring, holes),
      bank: bankWidth(t.source, climb),
    };
  });

  if (terraces.length === 0 && flights.length === 0) return FLAT_TERRAIN;

  /** Index of the innermost terrace holding the point, or -1. */
  const innermost = (e: number, n: number): number => {
    let best = -1;
    for (let i = 0; i < terraces.length; i++) {
      const t = terraces[i]!;
      if (!inBox(e, n, t.bbox) || !pointInRing(e, n, t.ring)) continue;
      if (best < 0 || t.area < terraces[best]!.area) best = i;
    }
    return best;
  };

  return {
    flat: false,
    terraces,
    flights,
    heightAt(e, n) {
      for (const f of flights) {
        const share = flightShare(f, e, n);
        if (share !== undefined) return f.base + f.rise * share;
      }
      const at = innermost(e, n);
      let height = at >= 0 ? terraces[at]!.z : 0;
      // On a bank: falling from a slope-edged terrace to the ground it
      // stands in (only where that ground is the level here).
      for (const t of terraces) {
        if (t.bank === 0 || t.parent !== at || !inBox(e, n, t.bbox, t.bank))
          continue;
        const d = distanceToRing(e, n, t.ring);
        if (d >= t.bank) continue;
        const bankHeight = t.z + (t.surround - t.z) * (d / t.bank);
        height =
          t.z > t.surround
            ? Math.max(height, bankHeight)
            : Math.min(height, bankHeight);
      }
      return height;
    },
  };
}

const cache = new WeakMap<Furniture, Terrain>();

/** The terrain of a collection, built once per loaded file. */
export function terrainOf(furniture: Furniture | undefined): Terrain {
  if (!furniture) return FLAT_TERRAIN;
  let terrain = cache.get(furniture);
  if (!terrain) {
    terrain = createTerrain(furniture);
    cache.set(furniture, terrain);
  }
  return terrain;
}

/**
 * Where an object placed at `base_z` stands: an explicit height wins; the
 * contract's default 0 means "on the ground here".
 */
export function standingHeight(
  terrain: Terrain,
  baseZ: number,
  [east, north]: XY,
): number {
  return baseZ !== 0 ? baseZ : terrain.heightAt(east, north);
}

/**
 * The ground a block stands on: the lowest ground at its corners, so no wall
 * floats above a lower yard; the higher sides run into their terrace.
 */
export function groundUnder(terrain: Terrain, outline: readonly XY[]): number {
  if (terrain.terraces.length === 0 || outline.length === 0) return 0;
  return Math.min(...outline.map(([e, n]) => terrain.heightAt(e, n)));
}
