import {
  BoxGeometry,
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  Euler,
  ExtrudeGeometry,
  Float32BufferAttribute,
  IcosahedronGeometry,
  Matrix4,
  Quaternion,
  Shape,
  SphereGeometry,
  TorusGeometry,
  Vector2,
  Vector3,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type { Furniture, ItemKind, RailSide, SeatingGroup } from './furniture';
import { openRing } from './geometry';
import { PAVE, type Pave, paveOf } from './paving';
import {
  distanceToRing,
  type Flight,
  flightCorners,
  pointInRing,
  signedArea,
  standingHeight,
  type Terrain,
  type TerraceShape,
} from './terrain';

type XY = [number, number];
type V3 = [number, number, number];

/**
 * Street-level materials, picked to sit with the map's warm paving and the
 * ochre campus (docs/design-system.md): pale limestone for steps and
 * copings, a warmer stone for retaining walls, charcoal metal, teak benches.
 */
export const furnitureColors = {
  paving: '#E4E1DA',
  wall: '#CBBDA3',
  coping: '#EFE9DC',
  kerb: '#D9D4CA',
  bank: '#97B873',
  tread: '#EAE3D5',
  nosing: '#B7AC97',
  riser: '#D4CAB7',
  ramp: '#DCD5C7',
  rampKerb: '#EBE6DC',
  metal: '#394049',
  wood: '#B07E52',
  tableTop: '#F3F0EA',
  seat: '#D9C7A5',
  canopy: '#F6F1E7',
  planter: '#D3CAB9',
  soil: '#5E4B3B',
  shrub: '#6F9B57',
  bin: '#46514C',
  band: '#ECE8DF',
  steel: '#AEB5BB',
  lens: '#F2EFE8',
  mast: '#E9ECEE',
  flag: '#D7262E',
  booth: '#F1F0EC',
  boothGlass: '#5B6E7A',
  board: '#2F4C8C',
  kiosk: '#5B2A86',
  kioskCanopy: '#D63A8C',
  seal: '#A3243B',
  sealRing: '#3D2B2E',
  plinth: '#F2EFE8',
  letters: '#F7F7F5',
  bronze: '#5E6B64',
  fenceBrick: '#8E3B2B',
  fenceBand: '#ECE7DC',
  iron: '#1E2124',
  gilt: '#C9A245',
  standRed: '#C42A30',
  hedge: '#4E7D3A',
  hedgeTop: '#5E8F45',
} as const;

/** How far walls reach below their foot, so no seam shows at the ground. */
const BURY_M = 0.3;
/** Coping on top of a retaining wall: an upstand that marks the edge. */
export const COPING = { width: 0.32, height: 0.12 } as const;
/** Darker anti-slip band at each tread's front edge. */
const NOSING_M = 0.06;
/** Ramp edges: a small upstand on both sides. */
const RAMP_KERB = { width: 0.14, height: 0.1 } as const;
/** A ramp's foot starts this high, so flat ground layers never cover it. */
const RAMP_LIP_M = 0.06;

/** Handrails: height above the pitch line, end extensions, post rhythm. */
export const RAIL = {
  height: 0.9,
  extension: 0.3,
  inset: 0.1,
  postSpacing: 1.2,
  bar: 0.045,
} as const;

const UP: V3 = [0, 1, 0];

/** ENU metres and height -> three.js world. */
const w = (e: number, n: number, h: number): V3 => [e, h, -n];
/** An ENU direction as a world direction. */
const wDir = ([e, n]: XY, up = 0): V3 => [e, up, -n];

/** Flat-shaded faces with vertex colours, merged into one geometry. */
class Faces {
  private readonly positions: number[] = [];
  private readonly colors: number[] = [];
  private readonly paving: number[] = [];
  private readonly tint = new Color();

  /**
   * A planar convex polygon, turned so its front faces `towards`, with the
   * paving drawn on it (paving.ts).
   */
  add(points: V3[], color: string, towards: V3, pave: Pave = PAVE.none): void {
    if (points.length < 3) return;
    const [p0, p1, p2] = points as [V3, V3, V3];
    const ux = p1[0] - p0[0];
    const uy = p1[1] - p0[1];
    const uz = p1[2] - p0[2];
    const vx = p2[0] - p0[0];
    const vy = p2[1] - p0[1];
    const vz = p2[2] - p0[2];
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    if (Math.hypot(nx, ny, nz) < 1e-9) return;
    const facing = nx * towards[0] + ny * towards[1] + nz * towards[2];
    const ordered = facing < 0 ? [...points].reverse() : points;
    this.tint.set(color);
    for (let i = 1; i + 1 < ordered.length; i++) {
      for (const p of [ordered[0]!, ordered[i]!, ordered[i + 1]!]) {
        this.positions.push(p[0], p[1], p[2]);
        this.colors.push(this.tint.r, this.tint.g, this.tint.b);
        this.paving.push(pave);
      }
    }
  }

  get triangleCount(): number {
    return this.positions.length / 9;
  }

  build(): BufferGeometry | undefined {
    if (this.positions.length === 0) return undefined;
    const geometry = new BufferGeometry();
    geometry.setAttribute(
      'position',
      new Float32BufferAttribute(this.positions, 3),
    );
    geometry.setAttribute('color', new Float32BufferAttribute(this.colors, 3));
    geometry.setAttribute('paving', new Float32BufferAttribute(this.paving, 1));
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    return geometry;
  }
}

// ---------------------------------------------------------------- terraces

/** Ring offset by `d` metres (outward for a counter-clockwise ring), mitred. */
export function offsetRing(ring: XY[], d: number): XY[] {
  const outward = (a: XY, b: XY): XY => {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    return [dy / len, -dx / len];
  };
  return ring.map((p, i) => {
    const prev = ring[(i - 1 + ring.length) % ring.length]!;
    const next = ring[(i + 1) % ring.length]!;
    const n1 = outward(prev, p);
    const n2 = outward(p, next);
    const mx = n1[0] + n2[0];
    const my = n1[1] + n2[1];
    const len = Math.hypot(mx, my);
    if (len < 1e-6) return [p[0] + n1[0] * d, p[1] + n1[1] * d];
    const ux = mx / len;
    const uy = my / len;
    const scale = 1 / Math.max(ux * n1[0] + uy * n1[1], 0.4);
    return [p[0] + ux * d * scale, p[1] + uy * d * scale];
  });
}

/**
 * Stretches of a terrace edge a→b (as 0..1 along it) where a flight of
 * stairs or a ramp arrives at the terrace's level: the coping stops there.
 */
export function flightGaps(
  a: XY,
  b: XY,
  level: number,
  flights: readonly Flight[],
): [number, number][] {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return [];
  const ux = dx / len;
  const uy = dy / len;
  const gaps: [number, number][] = [];
  for (const f of flights) {
    const c = flightCorners(f);
    for (const [l, r, height] of [
      [c.topLeft, c.topRight, f.base + f.rise],
      [c.footLeft, c.footRight, f.base],
    ] as const) {
      if (Math.abs(height - level) > 0.35) continue;
      const mx = (l[0] + r[0]) / 2 - a[0];
      const my = (l[1] + r[1]) / 2 - a[1];
      if (Math.abs(ux * my - uy * mx) > 0.9) continue;
      // The end's corners, 5 cm wider, projected onto the edge.
      const ex = r[0] - l[0];
      const ey = r[1] - l[1];
      const k = 0.05 / (Math.hypot(ex, ey) || 1);
      const s1 = (l[0] - ex * k - a[0]) * ux + (l[1] - ey * k - a[1]) * uy;
      const s2 = (r[0] + ex * k - a[0]) * ux + (r[1] + ey * k - a[1]) * uy;
      const lo = Math.max(0, Math.min(s1, s2) / len);
      const hi = Math.min(1, Math.max(s1, s2) / len);
      if (hi > lo) gaps.push([lo, hi]);
    }
  }
  gaps.sort((p, q) => p[0] - q[0]);
  const merged: [number, number][] = [];
  for (const gap of gaps) {
    const last = merged[merged.length - 1];
    if (last && gap[0] <= last[1]) last[1] = Math.max(last[1], gap[1]);
    else merged.push([...gap]);
  }
  return merged;
}

const lerp2 = (a: XY, b: XY, t: number): XY => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
];

function addTerrace(
  faces: Faces,
  t: TerraceShape,
  flights: readonly Flight[],
): void {
  const c = furnitureColors;
  const pave = paveOf(t.id);
  for (let i = 0; i < t.triangles.length; i += 6) {
    faces.add(
      [
        w(t.triangles[i]!, t.triangles[i + 1]!, t.z),
        w(t.triangles[i + 2]!, t.triangles[i + 3]!, t.z),
        w(t.triangles[i + 4]!, t.triangles[i + 5]!, t.z),
      ],
      c.paving,
      UP,
      pave,
    );
  }
  const raised = t.z > t.surround;
  const low = Math.min(t.z, t.surround);
  const high = Math.max(t.z, t.surround);
  const bottom = low - (raised ? BURY_M : 0);
  const ring = t.ring;
  const bank = t.bank > 0 ? offsetRing(ring, t.bank) : undefined;
  const coping =
    t.edge === 'wall' && raised ? offsetRing(ring, -COPING.width) : undefined;
  const wallColor = t.edge === 'kerb' ? c.kerb : c.wall;

  for (let i = 0; i < ring.length; i++) {
    const j = (i + 1) % ring.length;
    const a = ring[i]!;
    const b = ring[j]!;
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (len < 1e-6) continue;
    const out: XY = [(b[1] - a[1]) / len, -(b[0] - a[0]) / len];
    const outward = wDir(out);
    const facing = raised ? outward : wDir([-out[0], -out[1]]);

    if (bank) {
      const a2 = bank[i]!;
      const b2 = bank[j]!;
      faces.add(
        [
          w(a[0], a[1], t.z),
          w(b[0], b[1], t.z),
          w(b2[0], b2[1], t.surround),
          w(a2[0], a2[1], t.surround),
        ],
        c.bank,
        UP,
      );
      continue;
    }
    if (!coping) {
      faces.add(
        [
          w(a[0], a[1], bottom),
          w(b[0], b[1], bottom),
          w(b[0], b[1], high),
          w(a[0], a[1], high),
        ],
        wallColor,
        facing,
      );
      continue;
    }

    // A retaining wall with its coping, open where flights arrive.
    const ai = coping[i]!;
    const bi = coping[j]!;
    const gaps = flightGaps(a, b, t.z, flights);
    const pieces: [number, number][] = [];
    let from = 0;
    for (const [lo, hi] of gaps) {
      if (lo > from) pieces.push([from, lo]);
      from = Math.max(from, hi);
    }
    if (from < 1) pieces.push([from, 1]);
    const wall = (s: number, e: number, top: number) => {
      const p = lerp2(a, b, s);
      const q = lerp2(a, b, e);
      faces.add(
        [
          w(p[0], p[1], bottom),
          w(q[0], q[1], bottom),
          w(q[0], q[1], top),
          w(p[0], p[1], top),
        ],
        c.wall,
        outward,
      );
    };
    for (const [lo, hi] of gaps) wall(lo, hi, t.z);
    const along = wDir([(b[0] - a[0]) / len, (b[1] - a[1]) / len]);
    const top = t.z + COPING.height;
    for (const [s, e] of pieces) {
      wall(s, e, top);
      const po = lerp2(a, b, s);
      const qo = lerp2(a, b, e);
      const pi = lerp2(ai, bi, s);
      const qi = lerp2(ai, bi, e);
      faces.add(
        [
          w(po[0], po[1], top),
          w(qo[0], qo[1], top),
          w(qi[0], qi[1], top),
          w(pi[0], pi[1], top),
        ],
        c.coping,
        UP,
      );
      faces.add(
        [
          w(pi[0], pi[1], t.z),
          w(qi[0], qi[1], t.z),
          w(qi[0], qi[1], top),
          w(pi[0], pi[1], top),
        ],
        c.coping,
        wDir([-out[0], -out[1]]),
      );
      const cap = (o: XY, n: XY, towards: V3) =>
        faces.add(
          [
            w(o[0], o[1], t.z),
            w(n[0], n[1], t.z),
            w(n[0], n[1], top),
            w(o[0], o[1], top),
          ],
          c.coping,
          towards,
        );
      if (s > 0) cap(po, pi, [-along[0], 0, -along[2]]);
      if (e < 1) cap(qo, qi, along);
    }
  }
}

// ---------------------------------------------------------- stairs, ramps

export interface Tread {
  /** Metres from the foot where the tread starts and ends. */
  from: number;
  to: number;
  /** Height of its walking surface. */
  top: number;
}

/** A flight cut into `steps` equal risers and goings. */
export function stairTreads(
  f: Flight,
  steps: number,
): { riser: number; going: number; treads: Tread[] } {
  const n = Math.max(1, Math.round(steps));
  const riser = f.rise / n;
  const going = f.run / n;
  const treads = Array.from({ length: n }, (_, i) => ({
    from: i * going,
    to: (i + 1) * going,
    top: f.base + (i + 1) * riser,
  }));
  return { riser, going, treads };
}

/**
 * A point in a flight's frame (along, to the left, height) in the world. A
 * fanned flight maps the frame onto its corners (bilinear), so its treads
 * widen or narrow across it and its sides follow the neighbours'.
 */
function inFlight(f: Flight, along: number, left: number, h: number): V3 {
  const c = f.corners;
  if (!c)
    return w(
      f.foot[0] + f.dir[0] * along + f.left[0] * left,
      f.foot[1] + f.dir[1] * along + f.left[1] * left,
      h,
    );
  const u = along / f.run;
  const v = (left / (f.width / 2) + 1) / 2;
  const p = lerp2(
    lerp2(c.footRight, c.footLeft, v),
    lerp2(c.topRight, c.topLeft, v),
    u,
  );
  return w(p[0], p[1], h);
}

/** Outward plan normal of the edge a→b, turned right of it. */
function rightOf(a: XY, b: XY): XY {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  return [dy / len, -dx / len];
}

function addStairs(faces: Faces, f: Flight, steps: number): void {
  const c = furnitureColors;
  const { riser, going, treads } = stairTreads(f, steps);
  const half = f.width / 2;
  const corners = flightCorners(f);
  // Sides and ends face out of the outline (a fanned flight's are skewed).
  const left = wDir(rightOf(corners.topLeft, corners.footLeft));
  const right = wDir(rightOf(corners.footRight, corners.topRight));
  const ahead = wDir(rightOf(corners.topRight, corners.topLeft));
  const bottom = f.base - BURY_M;
  const nose = Math.min(NOSING_M, going * 0.3);
  for (const { from, to, top } of treads) {
    const u = from / f.run;
    const down = wDir(
      rightOf(
        lerp2(corners.footLeft, corners.topLeft, u),
        lerp2(corners.footRight, corners.topRight, u),
      ),
    );
    const quad = (a0: number, a1: number, color: string) =>
      faces.add(
        [
          inFlight(f, a0, half, top),
          inFlight(f, a0, -half, top),
          inFlight(f, a1, -half, top),
          inFlight(f, a1, half, top),
        ],
        color,
        UP,
      );
    quad(from, from + nose, c.nosing);
    quad(from + nose, to, c.tread);
    faces.add(
      [
        inFlight(f, from, half, top - riser),
        inFlight(f, from, -half, top - riser),
        inFlight(f, from, -half, top),
        inFlight(f, from, half, top),
      ],
      c.riser,
      down,
    );
    for (const [side, towards] of [
      [half, left],
      [-half, right],
    ] as const) {
      faces.add(
        [
          inFlight(f, from, side, bottom),
          inFlight(f, to, side, bottom),
          inFlight(f, to, side, top),
          inFlight(f, from, side, top),
        ],
        c.wall,
        towards,
      );
    }
  }
  faces.add(
    [
      inFlight(f, f.run, half, bottom),
      inFlight(f, f.run, -half, bottom),
      inFlight(f, f.run, -half, f.base + f.rise),
      inFlight(f, f.run, half, f.base + f.rise),
    ],
    c.wall,
    ahead,
  );
}

/** Height of a ramp's walking surface `along` metres from its foot. */
function rampSurface(f: Flight, along: number): number {
  const k = Math.min(1, Math.max(0, along / f.run));
  return f.base + f.rise * k + RAMP_LIP_M * (1 - k);
}

function addRamp(faces: Faces, f: Flight): void {
  const c = furnitureColors;
  const half = f.width / 2;
  const inner = Math.max(0, half - RAMP_KERB.width);
  const bottom = f.base - BURY_M;
  const y0 = rampSurface(f, 0);
  const y1 = rampSurface(f, f.run);
  const kerb = RAMP_KERB.height;
  faces.add(
    [
      inFlight(f, 0, inner, y0),
      inFlight(f, 0, -inner, y0),
      inFlight(f, f.run, -inner, y1),
      inFlight(f, f.run, inner, y1),
    ],
    c.ramp,
    UP,
  );
  for (const side of [1, -1]) {
    const outer = side * half;
    const edge = side * inner;
    const sideward = wDir([f.left[0] * side, f.left[1] * side]);
    // Kerb: its top, the face towards the walking surface, the outer cheek.
    faces.add(
      [
        inFlight(f, 0, outer, y0 + kerb),
        inFlight(f, 0, edge, y0 + kerb),
        inFlight(f, f.run, edge, y1 + kerb),
        inFlight(f, f.run, outer, y1 + kerb),
      ],
      c.rampKerb,
      UP,
    );
    faces.add(
      [
        inFlight(f, 0, edge, y0),
        inFlight(f, f.run, edge, y1),
        inFlight(f, f.run, edge, y1 + kerb),
        inFlight(f, 0, edge, y0 + kerb),
      ],
      c.rampKerb,
      wDir([-f.left[0] * side, -f.left[1] * side]),
    );
    faces.add(
      [
        inFlight(f, 0, outer, bottom),
        inFlight(f, f.run, outer, bottom),
        inFlight(f, f.run, outer, y1 + kerb),
        inFlight(f, 0, outer, y0 + kerb),
      ],
      c.wall,
      sideward,
    );
  }
  for (const [along, h, towards] of [
    [0, y0, wDir([-f.dir[0], -f.dir[1]])],
    [f.run, y1, wDir(f.dir)],
  ] as const) {
    faces.add(
      [
        inFlight(f, along, half, bottom),
        inFlight(f, along, -half, bottom),
        inFlight(f, along, -half, h),
        inFlight(f, along, half, h),
      ],
      c.wall,
      towards,
    );
  }
}

/**
 * Terraces (paving, retaining walls with copings, banks, kerbs), stairs and
 * ramps: one vertex-coloured geometry, one draw call.
 */
export function masonryGeometry(
  furniture: Furniture,
  terrain: Terrain,
): BufferGeometry | undefined {
  const faces = new Faces();
  for (const t of terrain.terraces) addTerrace(faces, t, terrain.flights);
  const steps = new Map(furniture.stairs.map((s) => [s.id, s.steps]));
  for (const f of terrain.flights) {
    if (f.kind === 'stairs') addStairs(faces, f, steps.get(f.id) ?? 1);
    else addRamp(faces, f);
  }
  return faces.build();
}

// ---------------------------------------------------------------- railings

export interface RailPost {
  /** Metres from the foot of the flight (negative: before it). */
  along: number;
  bottom: number;
  top: number;
}

export interface FlightRail {
  posts: RailPost[];
  /** Handrail line in the flight's frame: [along, height]. */
  rail: XY[];
}

/**
 * A flight's handrail: parallel to the pitch line (through the nosings) at
 * RAIL.height, carried on past both ends level for RAIL.extension, on posts
 * standing on the treads every RAIL.postSpacing at most.
 */
export function flightRail(f: Flight, steps?: number): FlightRail {
  const stairs = f.kind === 'stairs' && steps !== undefined;
  const { riser, going } = stairs
    ? stairTreads(f, steps)
    : { riser: 0, going: 0 };
  const n = stairs ? Math.max(1, Math.round(steps)) : 0;
  const lastNosing = stairs ? (n - 1) * going : f.run;
  const floorAt = (a: number) => {
    if (a <= 0) return f.base;
    if (a >= f.run) return f.base + f.rise;
    if (!stairs) return rampSurface(f, a);
    return f.base + Math.min(n, Math.floor(a / going) + 1) * riser;
  };
  const pitchAt = (a: number) => {
    if (!stairs) return rampSurface(f, Math.min(f.run, Math.max(0, a)));
    const k = Math.min(lastNosing, Math.max(0, a));
    return lastNosing > 0
      ? f.base + riser + ((f.rise - riser) * k) / lastNosing
      : f.base + riser;
  };
  const railAt = (a: number) => pitchAt(a) + RAIL.height;
  const ext = RAIL.extension;
  const rail: XY[] = [
    [-ext, railAt(0)],
    [0, railAt(0)],
    [lastNosing, railAt(lastNosing)],
    [f.run + ext, railAt(lastNosing)],
  ].filter(
    (p, i, all) => i === 0 || Math.abs(p[0]! - all[i - 1]![0]!) > 1e-6,
  ) as XY[];

  const inner = Math.max(0, f.run - 0.3);
  const spans = Math.max(1, Math.ceil(inner / RAIL.postSpacing));
  const along = [
    -ext + 0.05,
    ...Array.from({ length: spans + 1 }, (_, i) => 0.15 + (inner * i) / spans),
    f.run + ext - 0.05,
  ];
  const railHeight = (a: number) => {
    for (let i = 1; i < rail.length; i++) {
      const [a0, h0] = rail[i - 1]!;
      const [a1, h1] = rail[i]!;
      if (a <= a1 || i === rail.length - 1)
        return h0 + ((h1 - h0) * (a - a0)) / (a1 - a0 || 1);
    }
    return rail[0]![1];
  };
  const posts = along.map((a) => ({
    along: a,
    bottom: floorAt(a),
    top: railHeight(a),
  }));
  return { posts, rail };
}

const sidesOf = (side: RailSide): number[] =>
  side === 'both'
    ? [1, -1]
    : side === 'left'
      ? [1]
      : side === 'right'
        ? [-1]
        : [];

/** A square bar from p to q, `thickness` thick. */
function bar(parts: BufferGeometry[], p: V3, q: V3, thickness: number): void {
  const d = new Vector3(q[0] - p[0], q[1] - p[1], q[2] - p[2]);
  const len = d.length();
  if (len < 1e-3) return;
  const x = d.divideScalar(len);
  const up = Math.abs(x.y) > 0.99 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0);
  const z = new Vector3().crossVectors(x, up).normalize();
  const y = new Vector3().crossVectors(z, x);
  const geometry = new BoxGeometry(len, thickness, thickness);
  geometry.applyMatrix4(
    new Matrix4()
      .makeBasis(x, y, z)
      .setPosition((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, (p[2] + q[2]) / 2),
  );
  parts.push(geometry);
}

/**
 * Every rail: the flights' handrails (on the sides they have them) and the
 * free-standing railings (posts, top rail and a mid rail). One geometry.
 */
export function railingGeometry(
  furniture: Furniture,
  terrain: Terrain,
): BufferGeometry | undefined {
  const parts: BufferGeometry[] = [];
  const sides = new Map<string, RailSide>([
    ...furniture.stairs.map((s) => [s.id, s.railings] as const),
    ...furniture.ramps.map((r) => [r.id, r.railings] as const),
  ]);
  const steps = new Map(furniture.stairs.map((s) => [s.id, s.steps]));
  for (const f of terrain.flights) {
    const { posts, rail } = flightRail(
      f,
      f.kind === 'stairs' ? steps.get(f.id) : undefined,
    );
    for (const side of sidesOf(sides.get(f.id) ?? 'none')) {
      const v = side * Math.max(0, f.width / 2 - RAIL.inset);
      for (const post of posts)
        bar(
          parts,
          inFlight(f, post.along, v, post.bottom),
          inFlight(f, post.along, v, post.top + RAIL.bar / 2),
          RAIL.bar,
        );
      for (let i = 1; i < rail.length; i++) {
        const [a0, h0] = rail[i - 1]!;
        const [a1, h1] = rail[i]!;
        bar(parts, inFlight(f, a0, v, h0), inFlight(f, a1, v, h1), RAIL.bar);
        // Knee rail halfway down, between the end posts.
        bar(
          parts,
          inFlight(f, a0, v, h0 - RAIL.height / 2),
          inFlight(f, a1, v, h1 - RAIL.height / 2),
          RAIL.bar * 0.6,
        );
      }
    }
  }
  for (const railing of furniture.railings) {
    if (railing.style === 'fence') continue;
    const line = railing.line;
    const base = railing.base_z;
    const top = base + railing.height_m;
    for (let i = 0; i < line.length; i++) {
      const [e, n] = line[i]!;
      if (i > 0) {
        const [pe, pn] = line[i - 1]!;
        const len = Math.hypot(e - pe, n - pn);
        const spans = Math.max(1, Math.ceil(len / 1.6));
        for (let k = 1; k < spans; k++) {
          const t = k / spans;
          const x = pe + (e - pe) * t;
          const y = pn + (n - pn) * t;
          bar(parts, w(x, y, base), w(x, y, top), RAIL.bar);
        }
        bar(parts, w(pe, pn, top), w(e, n, top), RAIL.bar * 1.1);
        bar(
          parts,
          w(pe, pn, base + railing.height_m * 0.5),
          w(e, n, base + railing.height_m * 0.5),
          RAIL.bar * 0.6,
        );
      }
      bar(parts, w(e, n, base), w(e, n, top), RAIL.bar);
    }
  }
  if (parts.length === 0) return undefined;
  const merged = mergeGeometries(parts, false);
  for (const part of parts) part.dispose();
  merged.computeBoundingSphere();
  return merged;
}

// ------------------------------------------------------------------ fence

/** The campus boundary fence: plinth and piers in brick, iron between. */
export const FENCE = {
  pierSpacing: 3,
  pier: 0.5,
  plinth: 0.7,
  plinthWidth: 0.36,
  barSpacing: 0.18,
  bar: 0.025,
  globe: 0.17,
} as const;

/** Pier feet along a fence line: at every corner and at most 3 m apart. */
export function fencePiers(line: readonly XY[]): XY[] {
  const out: XY[] = [];
  for (let i = 0; i < line.length; i++) {
    const [e, n] = line[i]!;
    if (i > 0) {
      const [pe, pn] = line[i - 1]!;
      const spans = Math.max(
        1,
        Math.ceil(Math.hypot(e - pe, n - pn) / FENCE.pierSpacing),
      );
      for (let k = 1; k < spans; k++)
        out.push([pe + ((e - pe) * k) / spans, pn + ((n - pn) * k) / spans]);
    }
    out.push([e, n]);
  }
  return out;
}

/**
 * Every boundary fence (railings with style "fence"): a brick plinth with a
 * white coping, brick piers banded in white, black iron bars with gilded
 * tips between them. Vertex-coloured, one geometry; the piers' globe lamps
 * are instances ('globe'), so they glow with the lanterns at night.
 */
export function fenceGeometry(
  furniture: Furniture,
): BufferGeometry | undefined {
  const c = furnitureColors;
  const parts: BufferGeometry[] = [];
  const box = (
    p: XY,
    angle: number,
    size: [number, number, number],
    bottom: number,
    color: string,
  ) => {
    const g = new BoxGeometry(size[0], size[1], size[2]);
    parts.push(
      piece(
        g,
        color,
        new Matrix4().compose(
          new Vector3(p[0], bottom + size[1] / 2, -p[1]),
          new Quaternion().setFromEuler(new Euler(0, angle, 0)),
          new Vector3(1, 1, 1),
        ),
      ),
    );
  };
  for (const railing of furniture.railings) {
    if (railing.style !== 'fence') continue;
    const base = railing.base_z;
    const height = railing.height_m;
    const line = railing.line as XY[];
    for (let i = 1; i < line.length; i++) {
      const a = line[i - 1]!;
      const b = line[i]!;
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (len < 1e-3) continue;
      // Box x along the run: world angle from east, north is -z.
      const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
      const mid: XY = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      box(
        mid,
        angle,
        [len, FENCE.plinth, FENCE.plinthWidth],
        base - 0.2,
        c.fenceBrick,
      );
      box(
        mid,
        angle,
        [len, 0.06, FENCE.plinthWidth + 0.06],
        base + FENCE.plinth - 0.2,
        c.fenceBand,
      );
      const bars = Math.floor(len / FENCE.barSpacing);
      const barBottom = base + FENCE.plinth - 0.14;
      const barTop = base + height - 0.12;
      for (let k = 1; k < bars; k++) {
        const t = k / bars;
        const p: XY = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
        box(
          p,
          angle,
          [FENCE.bar, barTop - barBottom, FENCE.bar],
          barBottom,
          c.iron,
        );
        box(p, angle, [0.05, 0.08, 0.05], barTop, c.gilt);
      }
      for (const h of [barBottom + 0.12, barTop - 0.18])
        box(mid, angle, [len, 0.04, 0.04], h, c.iron);
    }
    for (const p of fencePiers(line)) {
      const angle = 0;
      box(
        p,
        angle,
        [FENCE.pier, height + 0.2, FENCE.pier],
        base - 0.2,
        c.fenceBrick,
      );
      for (const h of [0.95, 1.3])
        box(
          p,
          angle,
          [FENCE.pier + 0.03, 0.06, FENCE.pier + 0.03],
          base + h,
          c.fenceBand,
        );
      box(
        p,
        angle,
        [FENCE.pier + 0.1, 0.09, FENCE.pier + 0.1],
        base + height,
        c.fenceBand,
      );
    }
  }
  if (parts.length === 0) return undefined;
  const merged = mergeGeometries(parts, false);
  for (const part of parts) part.dispose();
  merged.computeVertexNormals();
  merged.computeBoundingSphere();
  return merged;
}

// ------------------------------------------------------------- item models

/** What one instanced mesh draws: an item kind, or a part of one. */
export type InstanceKind =
  Exclude<ItemKind, 'bike_rack'> | 'hoop' | 'lens' | 'globe';

/** Length an item gets when the data leaves `length_m` out, metres. */
export const DEFAULT_LENGTH: Partial<Record<ItemKind, number>> = {
  bench: 1.8,
  planter: 0.8,
  bike_rack: 2.25,
  umbrella: 2.6,
  flagpole: 9,
  sign: 1.2,
  hedge: 2,
  emblem: 4.5,
  letters: 4.2,
};

/** Lantern glass centres on a lamp's cross-arm (x) and their height. */
const LANTERN_X = [-0.42, 0.42] as const;
const LANTERN_Y = 4.12;

/** Bike-rack hoops stand this far apart. */
const HOOP_PITCH_M = 0.75;

function piece(
  geometry: BufferGeometry,
  color: string,
  matrix: Matrix4,
): BufferGeometry {
  const g = geometry.index ? geometry.toNonIndexed() : geometry;
  if (g !== geometry) geometry.dispose();
  g.applyMatrix4(matrix);
  g.deleteAttribute('uv');
  const tint = new Color(color);
  const colors = new Float32Array(g.getAttribute('position').count * 3);
  for (let i = 0; i < colors.length; i += 3) {
    colors[i] = tint.r;
    colors[i + 1] = tint.g;
    colors[i + 2] = tint.b;
  }
  g.setAttribute('color', new Float32BufferAttribute(colors, 3));
  return g;
}

const at = (x: number, y: number, z: number, rx = 0, ry = 0, rz = 0) =>
  new Matrix4().compose(
    new Vector3(x, y, z),
    new Quaternion().setFromEuler(new Euler(rx, ry, rz)),
    new Vector3(1, 1, 1),
  );

const scaled = (m: Matrix4, x: number, y: number, z: number) =>
  m.multiply(new Matrix4().makeScale(x, y, z));

/**
 * One item's model in its own frame: x along its length (1 m for the kinds
 * that stretch), y up, +z the way it faces. Vertex-coloured, flat-shaded.
 */
export function itemGeometry(kind: InstanceKind): BufferGeometry {
  const c = furnitureColors;
  const parts: BufferGeometry[] = [];
  const add = (g: BufferGeometry, color: string, m: Matrix4) =>
    parts.push(piece(g, color, m));
  switch (kind) {
    case 'bench':
      add(new BoxGeometry(1, 0.05, 0.44), c.wood, at(0, 0.43, 0.02));
      add(new BoxGeometry(1, 0.3, 0.04), c.wood, at(0, 0.7, -0.21, -0.2));
      for (const x of [-0.42, 0.42]) {
        add(new BoxGeometry(0.05, 0.42, 0.05), c.metal, at(x, 0.21, 0.17));
        add(new BoxGeometry(0.05, 0.86, 0.05), c.metal, at(x, 0.43, -0.2));
        add(new BoxGeometry(0.05, 0.04, 0.42), c.metal, at(x, 0.39, 0));
      }
      break;
    case 'table':
      add(
        new CylinderGeometry(0.36, 0.36, 0.03, 20),
        c.tableTop,
        at(0, 0.74, 0),
      );
      add(new CylinderGeometry(0.03, 0.03, 0.72, 6), c.metal, at(0, 0.36, 0));
      add(new CylinderGeometry(0.2, 0.22, 0.03, 12), c.metal, at(0, 0.015, 0));
      break;
    case 'chair':
      add(new BoxGeometry(0.42, 0.04, 0.42), c.seat, at(0, 0.45, 0));
      add(new BoxGeometry(0.42, 0.34, 0.035), c.seat, at(0, 0.66, -0.2, -0.12));
      for (const x of [-0.18, 0.18])
        for (const z of [-0.18, 0.18])
          add(
            new CylinderGeometry(0.015, 0.015, 0.45, 5),
            c.metal,
            at(x, 0.225, z),
          );
      break;
    case 'umbrella':
      // Canopy radius 1: instances scale it to their size.
      add(new CylinderGeometry(0.022, 0.022, 2.5, 6), c.metal, at(0, 1.25, 0));
      add(new ConeGeometry(1, 0.42, 8, 1), c.canopy, at(0, 2.41, 0));
      add(
        new CylinderGeometry(1, 1, 0.09, 8, 1, true),
        c.canopy,
        at(0, 2.16, 0),
      );
      add(new CylinderGeometry(0.03, 0.03, 0.08, 6), c.metal, at(0, 2.66, 0));
      break;
    case 'planter':
      add(new BoxGeometry(1, 0.55, 0.7), c.planter, at(0, 0.275, 0));
      add(new BoxGeometry(0.92, 0.02, 0.62), c.soil, at(0, 0.55, 0));
      add(
        new IcosahedronGeometry(1, 1),
        c.shrub,
        scaled(at(0, 0.82, 0), 0.46, 0.4, 0.33),
      );
      break;
    case 'bollard':
      add(
        new CylinderGeometry(0.085, 0.095, 0.85, 10),
        c.metal,
        at(0, 0.425, 0),
      );
      add(new CylinderGeometry(0.097, 0.097, 0.05, 10), c.band, at(0, 0.74, 0));
      add(new CylinderGeometry(0.06, 0.085, 0.04, 10), c.metal, at(0, 0.87, 0));
      break;
    case 'bin':
      add(new CylinderGeometry(0.24, 0.22, 0.82, 14), c.bin, at(0, 0.41, 0));
      add(new CylinderGeometry(0.26, 0.26, 0.07, 14), c.metal, at(0, 0.855, 0));
      break;
    case 'lamp':
      // The campus's cast-iron post: a fluted base, a slim shaft and a
      // cross-arm carrying two lanterns (their glass is the 'lens').
      add(new CylinderGeometry(0.15, 0.2, 0.55, 8), c.metal, at(0, 0.275, 0));
      add(new CylinderGeometry(0.11, 0.15, 0.12, 8), c.metal, at(0, 0.6, 0));
      add(new CylinderGeometry(0.045, 0.065, 3.3, 8), c.metal, at(0, 2.3, 0));
      add(new CylinderGeometry(0.08, 0.08, 0.14, 8), c.metal, at(0, 3.95, 0));
      add(new BoxGeometry(0.95, 0.05, 0.05), c.metal, at(0, 4.0, 0));
      for (const x of LANTERN_X) {
        add(new BoxGeometry(0.22, 0.04, 0.22), c.metal, at(x, 3.97, 0));
        add(
          new ConeGeometry(0.19, 0.2, 4, 1),
          c.metal,
          at(x, LANTERN_Y + 0.23, 0, 0, Math.PI / 4),
        );
        add(
          new SphereGeometry(0.035, 6, 4),
          c.metal,
          at(x, LANTERN_Y + 0.36, 0),
        );
      }
      break;
    case 'flagpole':
      // Mast 1 m tall (instances scale y to its height); the flag near the
      // top is unscaled in instances, so it is drawn in mast units here and
      // kept small: 1.5 x 1 m at a 9 m mast reads well from above.
      add(new CylinderGeometry(0.006, 0.009, 1, 8), c.mast, at(0, 0.5, 0));
      add(new BoxGeometry(0.17, 0.11, 0.003), c.flag, at(0.09, 0.9, 0));
      break;
    case 'booth':
      // A white cabin with a band of glass and a flat overhanging roof.
      add(new BoxGeometry(1.4, 2.3, 1.4), c.booth, at(0, 1.15, 0));
      add(new BoxGeometry(1.42, 0.9, 1.42), c.boothGlass, at(0, 1.45, 0));
      add(new BoxGeometry(1.7, 0.12, 1.7), c.booth, at(0, 2.36, 0));
      break;
    case 'kiosk':
      // A small stand, 1.5 m wide: a coloured body, a shelf front lighter
      // than it, and a canopy that leans out over the customer's side (+z).
      add(new BoxGeometry(1.5, 2.1, 1.0), c.kiosk, at(0, 1.05, 0));
      add(new BoxGeometry(1.2, 1.0, 0.04), c.tableTop, at(0, 1.1, 0.51));
      add(new BoxGeometry(1.7, 0.08, 1.5), c.kioskCanopy, at(0, 2.2, 0.2));
      break;
    case 'emblem': {
      // The seal, 1 m across (instances scale it uniformly to its
      // diameter): two stepped white plinth rings, then the red disc tilted
      // back towards +z so it reads from the plaza, its dark lettering ring.
      add(new CylinderGeometry(0.5, 0.5, 0.05, 32), c.plinth, at(0, 0.025, 0));
      add(new CylinderGeometry(0.47, 0.47, 0.07, 32), c.plinth, at(0, 0.08, 0));
      const tilt = 0.32;
      add(
        new CylinderGeometry(0.45, 0.45, 0.04, 32),
        c.seal,
        at(0, 0.17, 0, tilt),
      );
      // The ring sits on the disc's face: along its normal (0, cos, sin).
      add(
        new TorusGeometry(0.33, 0.012, 4, 32),
        c.sealRing,
        at(
          0,
          0.17 + 0.025 * Math.cos(tilt),
          0.025 * Math.sin(tilt),
          tilt - Math.PI / 2,
        ),
      );
      break;
    }
    case 'letters': {
      // "❤IAU", 1 m wide in all (instances stretch x to the word's width),
      // 1.75 m tall and 0.5 m deep: a red heart in the left quarter, then the
      // white block letters. x is in word widths, y and z in metres.
      const t = 0.06;
      const h = 1.75;
      const d = 0.5;
      const bar = (x: number, w: number, y = h / 2, hh = h, rz = 0) =>
        add(new BoxGeometry(w, hh, d), c.letters, at(x, y, 0, 0, 0, rz));
      bar(-0.15, t);
      // A: two legs leaning in, and its crossbar.
      bar(0.03, t, h / 2, h * 1.01, -0.05);
      bar(0.17, t, h / 2, h * 1.01, 0.05);
      bar(0.1, 0.12, h * 0.4, t * 2);
      // U: two posts and a bottom.
      bar(0.32, t);
      bar(0.48, t);
      bar(0.4, 0.22, t, t * 2);
      // The heart: the classic curve, 0.26 wide and 1.4 m tall.
      const heart = new Shape();
      for (let i = 0; i <= 48; i++) {
        const a = (i / 48) * Math.PI * 2;
        const x = 16 * Math.sin(a) ** 3;
        const y =
          13 * Math.cos(a) -
          5 * Math.cos(2 * a) -
          2 * Math.cos(3 * a) -
          Math.cos(4 * a);
        const p = new Vector2(-0.37 + (x / 32) * 0.26, 1.07 + (y / 29) * 1.4);
        if (i === 0) heart.moveTo(p.x, p.y);
        else heart.lineTo(p.x, p.y);
      }
      add(
        new ExtrudeGeometry(heart, { depth: d, bevelEnabled: false }),
        c.flag,
        at(0, 0, -d / 2),
      );
      break;
    }
    case 'statue': {
      // A life-size bronze rhino, its head towards +z: a rounded body on
      // four stocky legs, the head lower than the shoulders, a horn.
      const body = new SphereGeometry(0.5, 12, 8);
      body.scale(0.85, 0.75, 1.6);
      add(body, c.bronze, at(0, 1.05, 0));
      for (const x of [-0.26, 0.26])
        for (const z of [-0.5, 0.5])
          add(
            new CylinderGeometry(0.12, 0.14, 0.7, 8),
            c.bronze,
            at(x, 0.35, z),
          );
      add(new BoxGeometry(0.42, 0.42, 0.62), c.bronze, at(0, 0.9, 1.0, 0.35));
      add(new ConeGeometry(0.08, 0.38, 8), c.bronze, at(0, 1.18, 1.27, 0.5));
      break;
    }
    case 'topiary':
      // A box shrub clipped to a ball over a short trunk, 1.1 m tall.
      add(new CylinderGeometry(0.06, 0.08, 0.3, 6), c.soil, at(0, 0.15, 0));
      add(new SphereGeometry(0.45, 10, 8), c.hedge, at(0, 0.66, 0));
      break;
    case 'hedge':
      // A clipped box hedge, 1 m long (instances stretch x), 0.75 m tall,
      // its top a little lighter and narrower: it reads as soft from above.
      add(new BoxGeometry(1, 0.62, 0.62), c.hedge, at(0, 0.31, 0));
      add(new BoxGeometry(0.98, 0.14, 0.54), c.hedgeTop, at(0, 0.68, 0));
      break;
    case 'sign':
      // A board 1 m wide (instances stretch x) on two posts.
      add(new BoxGeometry(1, 1.1, 0.08), c.board, at(0, 1.45, 0));
      for (const x of [-0.42, 0.42])
        add(new BoxGeometry(0.06, 0.95, 0.06), c.metal, at(x, 0.47, 0));
      break;
    case 'stand':
      // An info lectern: a post and a red board tilted back towards +z.
      add(new BoxGeometry(0.1, 0.9, 0.1), c.metal, at(0, 0.45, 0));
      add(new BoxGeometry(0.75, 0.55, 0.05), c.standRed, at(0, 1.05, 0, -0.55));
      break;
    case 'globe':
      // A fence pier's lamp: a white globe on a small black collar.
      add(new CylinderGeometry(0.07, 0.09, 0.08, 10), c.metal, at(0, 0.04, 0));
      add(new SphereGeometry(FENCE.globe, 14, 10), c.lens, at(0, 0.24, 0));
      break;
    case 'lens':
      for (const x of LANTERN_X)
        add(new BoxGeometry(0.17, 0.24, 0.17), c.lens, at(x, LANTERN_Y, 0));
      break;
    case 'hoop': {
      // An inverted U across the rack's length, 0.82 m tall.
      const r = 0.32;
      add(
        new TorusGeometry(r, 0.022, 6, 14, Math.PI),
        c.steel,
        at(0, 0.5, 0, 0, Math.PI / 2),
      );
      for (const z of [-r, r])
        add(
          new CylinderGeometry(0.022, 0.022, 0.5, 6),
          c.steel,
          at(0, 0.25, z),
        );
      break;
    }
  }
  const merged = mergeGeometries(parts, false);
  for (const part of parts) part.dispose();
  merged.computeVertexNormals();
  merged.computeBoundingSphere();
  return merged;
}

// ---------------------------------------------------------------- seating

/** One placed thing: where, the compass bearing it faces, its size. */
export interface Placement {
  at: XY;
  heading: number;
  /** Uniform size factor in plan (an umbrella's canopy radius, m). */
  size?: number;
}

export interface SeatingLayout {
  tables: Placement[];
  chairs: Placement[];
  umbrellas: Placement[];
  /** Distance between neighbouring tables, metres. */
  pitch: number;
}

/** Closest table pitch: a table with chairs needs about this much. */
const MIN_PITCH_M = 1.75;
/** Closest pitch under umbrellas: canopies at least 2 m across, apart. */
const MIN_UMBRELLA_PITCH_M = 2.2;
/** A canopy's radius as a share of the pitch, so neighbours keep a gap. */
const CANOPY_SHARE = 0.46;
const MAX_CANOPY_M = 1.5;
/** Tables keep this far from the area's edge (a chair's depth). */
const SEAT_MARGIN_M = 0.55;
const CHAIR_RADIUS_M = 0.62;
/**
 * Table centres keep this far from a railing or fence, so the chairs, and the
 * canopy over them, stay on the café's side of it.
 */
const BARRIER_CLEARANCE_M = 1.0;
const UMBRELLA_BARRIER_CLEARANCE_M = MAX_CANOPY_M;

/** Stable 0..1 noise from a string and an index. */
function noise(seed: string, i: number): number {
  let h = 0x811c9dc5 ^ i;
  for (let k = 0; k < seed.length; k++) {
    h ^= seed.charCodeAt(k);
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 13;
  h = Math.imul(h, 0x5bd1e995);
  h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}

/** Compass bearing (degrees) of an ENU direction. */
const bearing = (e: number, n: number) =>
  ((((Math.atan2(e, n) * 180) / Math.PI) % 360) + 360) % 360;

/**
 * Café tables on a grid aligned with the area's longest side, as far apart
 * as the area allows; chairs round each table facing it, a little askew
 * (they move every day); an umbrella over each table when the café has them,
 * clear of its neighbours'. Nothing stands across a `barriers` line
 * (railings and fences): a sketched area may reach over one.
 */
export function seatingLayout(
  group: SeatingGroup,
  barriers: readonly XY[][] = [],
): SeatingLayout {
  let ring = openRing(group.outline);
  if (signedArea(ring) < 0) ring = [...ring].reverse();
  const area = signedArea(ring);
  // Area-weighted centroid.
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < ring.length; i++) {
    const [ax, ay] = ring[i]!;
    const [bx, by] = ring[(i + 1) % ring.length]!;
    const k = ax * by - bx * ay;
    cx += (ax + bx) * k;
    cy += (ay + by) * k;
  }
  cx /= 6 * area || 1;
  cy /= 6 * area || 1;
  let theta = 0;
  let longest = 0;
  for (let i = 0; i < ring.length; i++) {
    const [ax, ay] = ring[i]!;
    const [bx, by] = ring[(i + 1) % ring.length]!;
    const len = Math.hypot(bx - ax, by - ay);
    if (len > longest) {
      longest = len;
      theta = Math.atan2(by - ay, bx - ax);
    }
  }
  const ux: XY = [Math.cos(theta), Math.sin(theta)];
  const uy: XY = [-ux[1], ux[0]];
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  for (const [e, n] of ring) {
    const x = (e - cx) * ux[0] + (n - cy) * ux[1];
    const y = (e - cx) * uy[0] + (n - cy) * uy[1];
    x0 = Math.min(x0, x);
    x1 = Math.max(x1, x);
    y0 = Math.min(y0, y);
    y1 = Math.max(y1, y);
  }
  const clearance = group.umbrellas
    ? UMBRELLA_BARRIER_CLEARANCE_M
    : BARRIER_CLEARANCE_M;
  const clearOfBarriers = (e: number, n: number) =>
    barriers.every((line) =>
      line
        .slice(1)
        .every((b, i) => distanceToRing(e, n, [line[i]!, b]) >= clearance),
    );
  const fits = ([e, n]: XY) =>
    pointInRing(e, n, ring) &&
    distanceToRing(e, n, ring) >= SEAT_MARGIN_M &&
    clearOfBarriers(e, n);
  const grid = (s: number): XY[] => {
    let best: XY[] = [];
    for (const phase of [0, 0.5]) {
      const nx = Math.floor((x1 - x0) / s) + 1;
      const ny = Math.floor((y1 - y0) / s) + 1;
      const points: XY[] = [];
      for (let i = 0; i < nx + 1; i++) {
        for (let j = 0; j < ny + 1; j++) {
          const x = (x0 + x1) / 2 + (i - nx / 2 + phase) * s;
          const y = (y0 + y1) / 2 + (j - ny / 2 + phase) * s;
          const p: XY = [
            cx + ux[0] * x + uy[0] * y,
            cy + ux[1] * x + uy[1] * y,
          ];
          if (fits(p)) points.push(p);
        }
      }
      if (points.length > best.length) best = points;
    }
    return best;
  };

  const wanted = group.tables;
  const minPitch = group.umbrellas ? MIN_UMBRELLA_PITCH_M : MIN_PITCH_M;
  let pitch = Math.min(6, Math.max(minPitch, Math.sqrt(area / wanted)));
  let points = grid(pitch);
  if (points.length >= wanted) {
    // Spread out as far as the area allows.
    while (pitch < 6) {
      const wider = grid(pitch * 1.05);
      if (wider.length < wanted) break;
      pitch *= 1.05;
      points = wider;
    }
  } else {
    while (points.length < wanted && pitch > minPitch) {
      pitch = Math.max(minPitch, pitch * 0.95);
      points = grid(pitch);
    }
  }
  if (points.length === 0 && clearOfBarriers(cx, cy)) points = [[cx, cy]];
  points = points
    .map((p) => ({ p, d: Math.hypot(p[0] - cx, p[1] - cy) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, wanted)
    .map(({ p }) => p);

  const seats = group.seats_per_table;
  const facing = bearing(uy[0], uy[1]);
  const tables: Placement[] = [];
  const chairs: Placement[] = [];
  const umbrellas: Placement[] = [];
  points.forEach((p, t) => {
    tables.push({ at: p, heading: facing });
    if (group.umbrellas)
      umbrellas.push({
        at: p,
        heading: facing,
        size: Math.min(MAX_CANOPY_M, pitch * CANOPY_SHARE),
      });
    for (let k = 0; k < seats; k++) {
      const jitter = (i: number) => noise(group.id, t * 64 + k * 4 + i) - 0.5;
      const phi =
        theta + Math.PI / 2 + (k * 2 * Math.PI) / seats + jitter(0) * 0.24;
      const r = CHAIR_RADIUS_M + jitter(1) * 0.1;
      const de = Math.cos(phi);
      const dn = Math.sin(phi);
      chairs.push({
        at: [p[0] + de * r, p[1] + dn * r],
        heading: (bearing(-de, -dn) + jitter(2) * 24 + 360) % 360,
      });
    }
  });
  return { tables, chairs, umbrellas, pitch };
}

// --------------------------------------------------------------- instances

/** World matrix of an item standing at `base`, facing `heading` degrees. */
export function itemMatrix(
  [east, north]: XY,
  base: number,
  heading: number,
  scale: V3 = [1, 1, 1],
): Matrix4 {
  return new Matrix4().compose(
    new Vector3(...w(east, north, base)),
    new Quaternion().setFromEuler(
      new Euler(0, Math.PI - (heading * Math.PI) / 180, 0),
    ),
    new Vector3(...scale),
  );
}

/**
 * Every instance to draw, by model: placed items (a bike rack becomes its
 * hoops, a lamp its post and its lens) and the café seating groups' tables,
 * chairs and umbrellas, all standing on the terrain.
 */
export function furnitureInstances(
  furniture: Furniture,
  terrain: Terrain,
): Map<InstanceKind, Matrix4[]> {
  const out = new Map<InstanceKind, Matrix4[]>();
  const push = (kind: InstanceKind, m: Matrix4) => {
    const list = out.get(kind);
    if (list) list.push(m);
    else out.set(kind, [m]);
  };
  for (const item of furniture.items) {
    const base = standingHeight(terrain, item.base_z, item.at);
    const length = item.length_m ?? DEFAULT_LENGTH[item.kind] ?? 1;
    const h = item.heading_deg;
    switch (item.kind) {
      case 'bench':
      case 'planter':
      case 'sign':
      case 'hedge':
        push(item.kind, itemMatrix(item.at, base, h, [length, 1, 1]));
        break;
      case 'emblem':
        push('emblem', itemMatrix(item.at, base, h, [length, length, length]));
        break;
      case 'letters':
        push('letters', itemMatrix(item.at, base, h, [length, 1, 1]));
        break;
      case 'flagpole':
        push(
          'flagpole',
          itemMatrix(item.at, base, h, [length, length, length]),
        );
        break;
      case 'umbrella':
        push(
          'umbrella',
          itemMatrix(item.at, base, h, [length / 2, 1, length / 2]),
        );
        break;
      case 'bike_rack': {
        const hoops = Math.max(1, Math.round(length / HOOP_PITCH_M));
        // Hoops in a row along the rack's length (across its heading).
        const rad = (h * Math.PI) / 180;
        const across: XY = [Math.cos(rad), -Math.sin(rad)];
        for (let i = 0; i < hoops; i++) {
          const o = (i - (hoops - 1) / 2) * HOOP_PITCH_M;
          push(
            'hoop',
            itemMatrix(
              [item.at[0] + across[0] * o, item.at[1] + across[1] * o],
              base,
              h,
            ),
          );
        }
        break;
      }
      case 'lamp':
        push('lamp', itemMatrix(item.at, base, h));
        push('lens', itemMatrix(item.at, base, h));
        break;
      default:
        push(item.kind, itemMatrix(item.at, base, h));
    }
  }
  for (const railing of furniture.railings) {
    if (railing.style !== 'fence') continue;
    for (const p of fencePiers(railing.line as XY[]))
      push('globe', itemMatrix(p, railing.base_z + railing.height_m + 0.09, 0));
  }
  const barrierLines = furniture.railings.map((r) => r.line as XY[]);
  for (const group of furniture.seating) {
    const ring = openRing(group.outline);
    let ce = 0;
    let cn = 0;
    for (const [e, n] of ring) {
      ce += e;
      cn += n;
    }
    const base = standingHeight(terrain, group.base_z, [
      ce / ring.length,
      cn / ring.length,
    ]);
    const layout = seatingLayout(group, barrierLines);
    for (const p of layout.tables)
      push('table', itemMatrix(p.at, base, p.heading));
    for (const p of layout.chairs)
      push('chair', itemMatrix(p.at, base, p.heading));
    for (const p of layout.umbrellas) {
      const r = p.size ?? 1.3;
      push('umbrella', itemMatrix(p.at, base, p.heading, [r, 1, r]));
    }
  }
  return out;
}
