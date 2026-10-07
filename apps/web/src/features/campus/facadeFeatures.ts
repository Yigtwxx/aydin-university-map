import { Color } from 'three';

import { MASONRY_MODE } from './facadeRecipe';
import type { Builder, BuildingMeta } from './massing';
import type { Facade, FacadeFeature } from './types';

/**
 * The few shapes that make a campus block recognisable (amap_contracts
 * .facade.Feature), built into the merged massing as plain geometry: E Blok's
 * drum, A Blok's entrance tower, door canopies, framed portals and coloured
 * bands. They rise with their block in the opening and carry no windows.
 *
 * Features stand at `at` [east, north] with their front towards the compass
 * bearing `facing_deg`; `width_m` runs across the front, `depth_m` along it.
 */

type Point = [number, number];

/** Room above a feature's height for its crown (lip, coping). */
const CROWN_M = 0.5;
/** A drum's lip overhangs by this much and is this thick. */
const LIP_OVERHANG_M = 0.15;
const LIP_M = 0.25;
/** A tower's coping overhangs by this much on each side and is this thick. */
const COPING_OVERHANG_M = 0.15;
const COPING_M = 0.4;
/** Bands stand this far proud of the wall, so they never z-fight with it. */
const BAND_PROUD_M = 0.06;

/**
 * Plan angle (radians, counter-clockwise from east) that turns a feature's
 * front (its local +y) to the compass bearing `facingDeg`.
 */
export function planAngle(facingDeg: number): number {
  return (-facingDeg * Math.PI) / 180;
}

/** Highest point of the block's features, m (0 without any). */
export function featuresTop(facade: Facade): number {
  let top = 0;
  for (const f of facade.features)
    top = Math.max(top, f.base_m + f.height_m + CROWN_M);
  return top;
}

/** The point (x across, y towards the front) of a feature in plan. */
function local(at: Point, angle: number, x: number, y: number): Point {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return [at[0] + x * cos - y * sin, at[1] + x * sin + y * cos];
}

function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

/** A counter-clockwise ring moved `d` metres outwards (mitred corners). */
export function offsetRing(ring: Point[], d: number): Point[] {
  const outward = (a: Point, b: Point): Point => {
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    return [(b[1] - a[1]) / len, -(b[0] - a[0]) / len];
  };
  return ring.map((p, i) => {
    const prev = ring[(i + ring.length - 1) % ring.length]!;
    const next = ring[(i + 1) % ring.length]!;
    const n1 = outward(prev, p);
    const n2 = outward(p, next);
    let mx = n1[0] + n2[0];
    let my = n1[1] + n2[1];
    const ml = Math.hypot(mx, my) || 1;
    mx /= ml;
    my /= ml;
    // Mitre, limited on sharp corners.
    const k = d / Math.max(0.35, mx * n1[0] + my * n1[1]);
    return [p[0] + mx * k, p[1] + my * k];
  });
}

function drum(
  builder: Builder,
  f: FacadeFeature,
  at: Point,
  meta: BuildingMeta,
) {
  const angle = planAngle(f.facing_deg);
  const rx = f.width_m / 2;
  const ry = f.depth_m / 2;
  const body = new Color(f.colour);
  const bottom = f.base_m;
  const top = f.base_m + f.height_m;
  if (f.accent) {
    // One accent stripe high on the drum, as on E Blok's stair tower.
    const band = clamp(f.height_m * 0.08, 0.35, 1.2);
    const mid = bottom + f.height_m * 0.72;
    const lo = mid - band / 2;
    const hi = mid + band / 2;
    const accent = new Color(f.accent);
    builder.drum(at, rx, ry, angle, bottom, lo, body, meta, false);
    builder.drum(at, rx, ry, angle, lo, hi, accent, meta, false);
    builder.drum(at, rx, ry, angle, hi, top, body, meta, false);
  } else {
    builder.drum(at, rx, ry, angle, bottom, top, body, meta, false);
  }
  // A slim lip crowns it.
  builder.drum(
    at,
    rx + LIP_OVERHANG_M,
    ry + LIP_OVERHANG_M,
    angle,
    top,
    top + LIP_M,
    body,
    meta,
    true,
    true,
  );
}

/**
 * A box rising from `base_m`, its walls in masonry (courses and a recessed
 * panel, facadeMaterial.ts) when the block's recipe is on the GPU.
 */
function tower(
  builder: Builder,
  f: FacadeFeature,
  at: Point,
  meta: BuildingMeta,
  masonry: BuildingMeta | undefined,
) {
  const angle = planAngle(f.facing_deg);
  const top = f.base_m + f.height_m;
  const colour = new Color(f.colour);
  if (masonry) {
    const walls = { ...masonry, storey: f.height_m, ground: f.base_m };
    const w = f.width_m / 2;
    const d = f.depth_m / 2;
    const ring: Point[] = [
      local(at, angle, -w, -d),
      local(at, angle, w, -d),
      local(at, angle, w, d),
      local(at, angle, -w, d),
    ];
    for (let i = 0; i < 4; i++)
      builder.wallQuad(
        ring[i]!,
        ring[(i + 1) % 4]!,
        f.base_m,
        top,
        colour,
        walls,
      );
    builder.cap(ring, [], top, colour, meta);
  } else {
    builder.box(
      at,
      [f.width_m, f.depth_m, f.height_m],
      angle,
      f.base_m,
      colour,
      meta,
    );
  }
  if (f.accent)
    // Coping in the accent (white stone on A Blok's brick tower).
    builder.box(
      at,
      [
        f.width_m + COPING_OVERHANG_M * 2,
        f.depth_m + COPING_OVERHANG_M * 2,
        COPING_M,
      ],
      angle,
      top - 0.1,
      new Color(f.accent),
      meta,
      true,
    );
}

/** A flat slab over a door; its top at base_m + height_m. */
function canopy(
  builder: Builder,
  f: FacadeFeature,
  at: Point,
  meta: BuildingMeta,
) {
  const angle = planAngle(f.facing_deg);
  const slab = Math.min(0.3, f.height_m * 0.12);
  const top = f.base_m + f.height_m;
  builder.box(
    at,
    [f.width_m, f.depth_m, slab],
    angle,
    top - slab,
    new Color(f.colour),
    meta,
    true,
  );
  if (f.accent)
    // Fascia: a slim edge in the accent round the slab.
    builder.box(
      at,
      [f.width_m + 0.06, f.depth_m + 0.06, slab * 0.55],
      angle,
      top - slab * 0.78,
      new Color(f.accent),
      meta,
      true,
    );
}

/** A framed door: two jambs, a lintel and the door set back behind them. */
function portal(
  builder: Builder,
  f: FacadeFeature,
  at: Point,
  meta: BuildingMeta,
  glass: Color,
) {
  const angle = planAngle(f.facing_deg);
  const frame = new Color(f.colour);
  const jamb = clamp(f.width_m * 0.14, 0.3, 0.9);
  const lintel = clamp(f.height_m * 0.16, 0.4, 1.2);
  const open = f.height_m - lintel;
  for (const side of [-1, 1])
    builder.box(
      local(at, angle, side * (f.width_m / 2 - jamb / 2), 0),
      [jamb, f.depth_m, open],
      angle,
      f.base_m,
      frame,
      meta,
    );
  builder.box(
    at,
    [f.width_m + 0.3, f.depth_m + 0.2, lintel],
    angle,
    f.base_m + open,
    frame,
    meta,
    true,
  );
  const inset = f.depth_m * 0.3;
  builder.box(
    local(at, angle, 0, -f.depth_m / 2 + inset / 2),
    [Math.max(0.2, f.width_m - jamb * 2), inset, open],
    angle,
    f.base_m,
    f.accent ? new Color(f.accent) : glass,
    meta,
  );
}

/** A coloured stripe round the whole block. */
function band(
  builder: Builder,
  ring: Point[],
  f: FacadeFeature,
  meta: BuildingMeta,
) {
  const out = offsetRing(ring, BAND_PROUD_M);
  const colour = new Color(f.colour);
  const top = f.base_m + f.height_m;
  for (let i = 0; i < out.length; i++)
    builder.wallQuad(
      out[i]!,
      out[(i + 1) % out.length]!,
      f.base_m,
      top,
      colour,
      meta,
      false,
    );
  builder.cap(out, [ring], top, colour, meta);
  if (f.base_m > 0) builder.cap(out, [ring], f.base_m, colour, meta, false);
}

/**
 * Add the recipe's features to `builder`. `ring` is the block's outline
 * (counter-clockwise, open); `meta` its massing meta (the opening's rise).
 */
export function buildFeatures(
  builder: Builder,
  ring: Point[],
  facade: Facade,
  meta: BuildingMeta,
): void {
  // Plain shapes: no windows, no recipe (their colours are their own).
  const plain: BuildingMeta = {
    ...meta,
    storey: 0,
    recipe: 0,
    windows: 0,
    groundFloor: 0,
  };
  // Masonry needs the block's recipe row (none once the table is full).
  const masonry: BuildingMeta | undefined =
    meta.recipe > 0
      ? { ...meta, windows: MASONRY_MODE, groundFloor: 0 }
      : undefined;
  const glass = new Color(facade.glass);
  for (const f of facade.features) {
    if (f.kind === 'band') {
      band(builder, ring, f, plain);
      continue;
    }
    if (!f.at) continue;
    switch (f.kind) {
      case 'drum':
        drum(builder, f, f.at, plain);
        break;
      case 'tower':
        tower(builder, f, f.at, plain, masonry);
        break;
      case 'canopy':
        canopy(builder, f, f.at, plain);
        break;
      case 'portal':
        portal(builder, f, f.at, plain, glass);
        break;
    }
  }
}
