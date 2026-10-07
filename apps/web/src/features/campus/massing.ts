import {
  BufferGeometry,
  Color,
  type DataTexture,
  Float32BufferAttribute,
  ShapeUtils,
  Uint8BufferAttribute,
  Vector2,
} from 'three';

import { buildFeatures, featuresTop } from './facadeFeatures';
import {
  facingOf,
  fitStoreys,
  GROUND_MODE,
  RecipeTable,
  sideOf,
  WINDOW_MODE,
} from './facadeRecipe';
import { centroid, introOrigin, riseStart } from './opening';
import { openRing } from './geometry';
import type { Building, BuildingStyle, Facade, Roof } from './types';

/**
 * Styled building massing: walls, roofs (flat with parapets, hipped tiles,
 * barrel vaults, domes and minarets) and rooftop fixtures, merged into one
 * geometry per material so the whole neighbourhood is a couple of draw calls.
 *
 * Every vertex carries what the facade shader needs (facadeMaterial.ts):
 *   aWall = (u along the wall in m, wall length, v above ground in m, storey m)
 *   aMeta = (style index, per-building seed 0..1, storeys, ground floor m)
 *   aFlags = bytes (shops at street level 0/1, facade recipe slot (0 = none),
 *            window kind, ground floor kind); see facadeRecipe.ts
 *   aRise = (intro time s the building starts to emerge, depth m it rises from)
 * Positions are three.js world space: x east, y up, z south.
 *
 * Blocks with a surveyed `facade` recipe take their colours, window rhythm
 * and ground floor from it (per side of the block) and add the features that
 * make them recognisable (facadeFeatures.ts). The recipes travel as a float
 * texture on the geometry (`massingRecipes`).
 */

export const STYLE_INDEX: Record<BuildingStyle | 'fixture', number> = {
  campus: 0,
  apartment: 1,
  house: 2,
  retail: 3,
  showroom: 4,
  office: 5,
  industrial: 6,
  hangar: 7,
  school: 8,
  dormitory: 9,
  worship: 10,
  hospital: 11,
  hotel: 12,
  sports: 13,
  canopy: 14,
  fixture: 15,
};

/** Extra height of the ground floor (shop fronts, lobbies), as in the pipeline. */
const GROUND_EXTRA_M: Partial<Record<BuildingStyle, number>> = {
  campus: 0.6,
  apartment: 0.4,
  retail: 0.8,
  showroom: 1.2,
  office: 0.8,
  school: 0.4,
  dormitory: 0.6,
  hospital: 0.8,
  hotel: 1.0,
};

const PARAPET_M = 0.9;

const palettes: Record<BuildingStyle, { walls: string[]; roofs: string[] }> = {
  campus: { walls: ['#F0BF56'], roofs: ['#E6DCC8'] },
  apartment: {
    walls: [
      '#EDE3D1',
      '#E8D6BF',
      '#F0E2CB',
      '#E4DFD6',
      '#F2EEE6',
      '#DCCDB9',
      '#E9CFB7',
      '#D8DCDD',
      '#E6D7A6',
      '#D9C2B0',
    ],
    roofs: ['#CFCAC0', '#BDB8AF', '#D8D3C8'],
  },
  house: {
    walls: ['#EFE5D3', '#E8D3BA', '#F3EDE2', '#E2CDB2', '#E6DDC9'],
    roofs: ['#CFCAC0'],
  },
  retail: { walls: ['#E5E3DF', '#D9D6D0', '#ECEAE6'], roofs: ['#BEBAB2'] },
  showroom: { walls: ['#3B4148', '#2F353B'], roofs: ['#9EA3A8'] },
  office: { walls: ['#C9D2D8', '#B8C4CC', '#D5D9DB'], roofs: ['#B5B8BA'] },
  industrial: {
    walls: ['#C7CCCF', '#B9C5CD', '#DADDDF', '#C2C6BE'],
    roofs: ['#A9AEB2', '#B6BBBE'],
  },
  hangar: { walls: ['#D3D7DA', '#C4CBD0', '#DDE1E3'], roofs: ['#B0B6BB'] },
  school: { walls: ['#E8BD8E', '#E2C9A0', '#D9A77F'], roofs: ['#C9C2B5'] },
  dormitory: { walls: ['#E4DCCD', '#E6D2BC'], roofs: ['#C8C2B6'] },
  worship: { walls: ['#EEE9DF'], roofs: ['#8E989E'] },
  hospital: { walls: ['#F1F2F0'], roofs: ['#C8CACB'] },
  hotel: { walls: ['#E9E3D9', '#E2D8C6'], roofs: ['#BDB7AD'] },
  sports: { walls: ['#DFE3E6', '#D2DAE0'], roofs: ['#B5BCC2'] },
  canopy: { walls: ['#F2F2F0'], roofs: ['#D0D0D0'] },
};

// Weathered Marseille tiles: muted, slightly brown terracotta.
const TILE_ROOFS = ['#A65F48', '#9A5A47', '#B06B52', '#8F5243', '#A8654C'];
const LEAD = new Color('#8E989E');
const STONE = new Color('#EEE9DF');
const SOLAR_PANEL = new Color('#26344A');
const TANK = new Color('#E6E6E3');
const HVAC = new Color('#C9CCCE');

/** Deterministic 0..1 from a string (FNV-1a), stable across reloads. */
export function seedOf(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return ((h >>> 0) % 100000) / 100000;
}

/** Small per-building shifts of hue, saturation and lightness. */
function varied(color: Color, seed: number): Color {
  const h = ((seed * 9.13) % 1) - 0.5;
  const s = ((seed * 4.71) % 1) - 0.5;
  const l = ((seed * 2.37) % 1) - 0.5;
  return color.offsetHSL(h * 0.02, s * 0.08, l * 0.07);
}

function pick<T>(items: T[], seed: number): T {
  return items[Math.min(items.length - 1, Math.floor(seed * items.length))]!;
}

/** Signed area in (east, north); positive = counter-clockwise. */
function signedArea(ring: [number, number][]): number {
  let a = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i]!;
    const [x2, y2] = ring[(i + 1) % ring.length]!;
    a += x1 * y2 - x2 * y1;
  }
  return a / 2;
}

function ccw(ring: [number, number][]): [number, number][] {
  const open = openRing(ring);
  return signedArea(open) < 0 ? [...open].reverse() : open;
}

function inside(p: [number, number], ring: [number, number][]): boolean {
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

export interface BuildingMeta {
  style: number;
  seed: number;
  storeys: number;
  storey: number;
  ground: number;
  shops: number;
  /** Opening (opening.ts): when it starts to emerge, and from how deep. */
  rise: number;
  sink: number;
  /** Facade recipe slot (facadeRecipe.ts), 0 without a recipe. */
  recipe: number;
  /** WINDOW_MODE and GROUND_MODE of this side of the block. */
  windows: number;
  groundFloor: number;
}

/** Growable vertex buffers for one merged geometry. */
export class Builder {
  private position: number[] = [];
  private normal: number[] = [];
  private color: number[] = [];
  private wall: number[] = [];
  private meta: number[] = [];
  private flags: number[] = [];
  private rise: number[] = [];

  /** One vertex in ENU (east, north, up). */
  private vertex(
    e: number,
    n: number,
    up: number,
    normal: [number, number, number],
    color: Color,
    wall: [number, number, number, number],
    meta: BuildingMeta,
  ) {
    this.position.push(e, up, -n);
    this.normal.push(normal[0], normal[2], -normal[1]);
    this.color.push(color.r, color.g, color.b);
    this.wall.push(...wall);
    this.meta.push(meta.style, meta.seed, meta.storeys, meta.ground);
    this.flags.push(meta.shops, meta.recipe, meta.windows, meta.groundFloor);
    this.rise.push(meta.rise, meta.sink);
  }

  /** Vertical wall quad from a to b (ENU), outward normal to the right of a->b. */
  wallQuad(
    a: [number, number],
    b: [number, number],
    bottom: number,
    top: number,
    color: Color,
    meta: BuildingMeta,
    facade = true,
  ) {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const length = Math.hypot(dx, dy);
    if (length < 0.05) return;
    const normal: [number, number, number] = [dy / length, -dx / length, 0];
    // No windows on parapets, slab edges and fixtures: storey height 0.
    const storey = facade ? meta.storey : 0;
    const w = (u: number, v: number): [number, number, number, number] => [
      u,
      length,
      v,
      storey,
    ];
    const v0: [number, number, number] = [a[0], a[1], bottom];
    const v1: [number, number, number] = [b[0], b[1], bottom];
    const v2: [number, number, number] = [b[0], b[1], top];
    const v3: [number, number, number] = [a[0], a[1], top];
    for (const [p, uv] of [
      [v0, w(0, bottom)],
      [v1, w(length, bottom)],
      [v2, w(length, top)],
      [v0, w(0, bottom)],
      [v2, w(length, top)],
      [v3, w(0, top)],
    ] as const)
      this.vertex(p[0], p[1], p[2], normal, color, uv, meta);
  }

  /** Triangle with a flat normal (ENU points, counter-clockwise seen from outside). */
  triangle(
    a: [number, number, number],
    b: [number, number, number],
    c: [number, number, number],
    color: Color,
    meta: BuildingMeta,
  ) {
    const ux = b[0] - a[0];
    const uy = b[1] - a[1];
    const uz = b[2] - a[2];
    const vx = c[0] - a[0];
    const vy = c[1] - a[1];
    const vz = c[2] - a[2];
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz) || 1;
    nx /= len;
    ny /= len;
    nz /= len;
    const flat: [number, number, number, number] = [0, 0, 0, 0];
    for (const p of [a, b, c])
      this.vertex(p[0], p[1], p[2], [nx, ny, nz], color, flat, meta);
  }

  /** Horizontal polygon (with optional holes) at height ``up``, facing up or down. */
  cap(
    outer: [number, number][],
    holes: [number, number][][],
    up: number,
    color: Color,
    meta: BuildingMeta,
    facingUp = true,
  ) {
    const contour = outer.map(([x, y]) => new Vector2(x, y));
    const holeVecs = holes.map((h) => h.map(([x, y]) => new Vector2(x, y)));
    const all = [...contour, ...holeVecs.flat()];
    const faces = ShapeUtils.triangulateShape(contour, holeVecs);
    const normal: [number, number, number] = [0, 0, facingUp ? 1 : -1];
    const flat: [number, number, number, number] = [0, 0, up, 0];
    for (const [i, j, k] of faces) {
      const order = facingUp ? [i, j, k] : [i, k, j];
      for (const index of order) {
        const p = all[index!]!;
        this.vertex(p.x, p.y, up, normal, color, flat, meta);
      }
    }
  }

  /** Axis-aligned-in-plan box rotated by ``angle`` around its centre. */
  box(
    centre: [number, number],
    size: [number, number, number],
    angle: number,
    base: number,
    color: Color,
    meta: BuildingMeta,
    capBottom = false,
  ) {
    const [cx, cy] = centre;
    const [sx, sy, sz] = size;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const corner = (x: number, y: number): [number, number] => [
      cx + x * cos - y * sin,
      cy + x * sin + y * cos,
    ];
    const ring: [number, number][] = [
      corner(-sx / 2, -sy / 2),
      corner(sx / 2, -sy / 2),
      corner(sx / 2, sy / 2),
      corner(-sx / 2, sy / 2),
    ];
    for (let i = 0; i < 4; i++)
      this.wallQuad(
        ring[i]!,
        ring[(i + 1) % 4]!,
        base,
        base + sz,
        color,
        meta,
        false,
      );
    this.cap(ring, [], base + sz, color, meta);
    if (capBottom) this.cap(ring, [], base, color, meta, false);
  }

  /**
   * Upright elliptic drum with smooth (radial) normals: radius ``rx`` along
   * the plan direction ``angle``, ``ry`` across it.
   */
  drum(
    centre: [number, number],
    rx: number,
    ry: number,
    angle: number,
    bottom: number,
    top: number,
    color: Color,
    meta: BuildingMeta,
    capTop = true,
    capBottom = false,
    segments = 32,
  ) {
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const points: { p: [number, number]; n: [number, number, number] }[] =
      Array.from({ length: segments }, (_, i) => {
        const t = (i / segments) * Math.PI * 2;
        const x = Math.cos(t) * rx;
        const y = Math.sin(t) * ry;
        // Gradient of the ellipse: the outward normal at (x, y).
        const nx = Math.cos(t) / rx;
        const ny = Math.sin(t) / ry;
        const len = Math.hypot(nx, ny);
        return {
          p: [centre[0] + x * cos - y * sin, centre[1] + x * sin + y * cos],
          n: [(nx * cos - ny * sin) / len, (nx * sin + ny * cos) / len, 0],
        };
      });
    const flat: [number, number, number, number] = [0, 0, 0, 0];
    for (let i = 0; i < segments; i++) {
      const a = points[i]!;
      const b = points[(i + 1) % segments]!;
      for (const [q, up] of [
        [a, bottom],
        [b, bottom],
        [b, top],
        [a, bottom],
        [b, top],
        [a, top],
      ] as const)
        this.vertex(q.p[0], q.p[1], up, q.n, color, flat, meta);
    }
    const ring = points.map((q) => q.p);
    if (capTop) this.cap(ring, [], top, color, meta);
    if (capBottom) this.cap(ring, [], bottom, color, meta, false);
  }

  /** Vertical cylinder (or cone when ``rTop`` is 0) around ``centre``. */
  cylinder(
    centre: [number, number],
    rBottom: number,
    rTop: number,
    bottom: number,
    top: number,
    segments: number,
    color: Color,
    meta: BuildingMeta,
    capTop = true,
  ) {
    const ring = (r: number): [number, number][] =>
      Array.from({ length: segments }, (_, i) => {
        const a = (i / segments) * Math.PI * 2;
        return [centre[0] + Math.cos(a) * r, centre[1] + Math.sin(a) * r];
      });
    const low = ring(rBottom);
    const high = ring(rTop);
    for (let i = 0; i < segments; i++) {
      const j = (i + 1) % segments;
      const a0: [number, number, number] = [...low[i]!, bottom];
      const a1: [number, number, number] = [...low[j]!, bottom];
      const b0: [number, number, number] = [...high[i]!, top];
      const b1: [number, number, number] = [...high[j]!, top];
      this.triangle(a0, a1, b1, color, meta);
      if (rTop > 0) this.triangle(a0, b1, b0, color, meta);
    }
    if (capTop && rTop > 0) this.cap(high, [], top, color, meta);
  }

  /** Hemisphere-ish dome of radius ``r`` sitting at ``base``. */
  dome(
    centre: [number, number],
    r: number,
    base: number,
    color: Color,
    meta: BuildingMeta,
  ) {
    const rings = 7;
    const segments = 24;
    const point = (i: number, j: number): [number, number, number] => {
      const phi = (i / rings) * (Math.PI / 2);
      const theta = (j / segments) * Math.PI * 2;
      const rr = Math.cos(phi) * r;
      return [
        centre[0] + Math.cos(theta) * rr,
        centre[1] + Math.sin(theta) * rr,
        base + Math.sin(phi) * r * 0.92,
      ];
    };
    for (let i = 0; i < rings; i++)
      for (let j = 0; j < segments; j++) {
        const a = point(i, j);
        const b = point(i, j + 1);
        const c = point(i + 1, j + 1);
        const d = point(i + 1, j);
        this.triangle(a, b, c, color, meta);
        if (i < rings - 1) this.triangle(a, c, d, color, meta);
      }
  }

  build(): BufferGeometry | undefined {
    if (this.position.length === 0) return undefined;
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(this.position, 3));
    g.setAttribute('normal', new Float32BufferAttribute(this.normal, 3));
    g.setAttribute('color', new Float32BufferAttribute(this.color, 3));
    g.setAttribute('aWall', new Float32BufferAttribute(this.wall, 4));
    g.setAttribute('aMeta', new Float32BufferAttribute(this.meta, 4));
    g.setAttribute('aFlags', new Uint8BufferAttribute(this.flags, 4));
    g.setAttribute('aRise', new Float32BufferAttribute(this.rise, 2));
    g.computeBoundingSphere();
    g.computeBoundingBox();
    return g;
  }
}

function metaOf(
  b: Building,
  style: BuildingStyle,
  seed: number,
  origin: [number, number],
): BuildingMeta {
  const ground = GROUND_EXTRA_M[style] ?? 0;
  const [ce, cn] = centroid(b.outline);
  const storeys = Math.max(1, b.levels ?? Math.round(b.height_m / 3.2));
  const fixedVolume =
    style === 'industrial' ||
    style === 'hangar' ||
    style === 'sports' ||
    style === 'worship' ||
    style === 'canopy';
  const storey = fixedVolume
    ? b.height_m / Math.max(1, Math.round(b.height_m / 4.5))
    : Math.max(2.6, (b.height_m - ground) / storeys);
  return {
    style: STYLE_INDEX[style],
    seed,
    storeys: fixedVolume ? Math.max(1, Math.round(b.height_m / 4.5)) : storeys,
    storey,
    ground: storey + ground,
    shops: b.shops || style === 'retail' ? 1 : 0,
    rise: riseStart(Math.hypot(ce - origin[0], cn - origin[1]), seed),
    sink: Math.max(tallest(b), b.facade ? featuresTop(b.facade) : 0) + 1,
    recipe: 0,
    windows: 0,
    groundFloor: 0,
  };
}

/** The recipe's floors and window kinds on top of the style's meta. */
function recipeMeta(
  b: Building,
  facade: Facade,
  meta: BuildingMeta,
  slot: number,
): BuildingMeta {
  const { ground, storey, upper } = fitStoreys(facade, b.height_m, b.levels);
  return {
    ...meta,
    storeys: upper,
    storey,
    ground,
    recipe: slot,
    windows: WINDOW_MODE[facade.windows],
    groundFloor: GROUND_MODE[facade.ground],
  };
}

/** How the wall from a to b looks: its colour and what the shader draws. */
type Look = (
  a: [number, number],
  b: [number, number],
) => { color: Color; meta: BuildingMeta };

const plain =
  (color: Color, meta: BuildingMeta): Look =>
  () => ({ color, meta });

/**
 * A recipe block's walls: the recipe, or the override for the compass
 * direction a wall faces (a glass front towards the street).
 */
function recipeLook(facade: Facade, wall: Color, meta: BuildingMeta): Look {
  const colours = new Map<string, Color>();
  return (a, b) => {
    const side = sideOf(facade, facingOf(a, b));
    if (!side) return { color: wall, meta };
    let color = wall;
    if (side.wall) {
      color = colours.get(side.wall) ?? new Color(side.wall);
      colours.set(side.wall, color);
    }
    return {
      color,
      meta: {
        ...meta,
        windows: side.windows ? WINDOW_MODE[side.windows] : meta.windows,
        groundFloor: side.ground ? GROUND_MODE[side.ground] : meta.groundFloor,
      },
    };
  };
}

/** Highest point of the building: roof, penthouse, dome or minaret. */
function tallest(b: Building): number {
  const roof = b.roof;
  if (!roof) return b.height_m + PARAPET_M;
  switch (roof.shape) {
    case 'hipped':
    case 'barrel':
      return b.height_m + roof.rise + 1;
    case 'dome':
      return Math.max(b.height_m + 2 + roof.radius * 2, roof.minaret_m + 2);
    case 'flat':
      return b.height_m + PARAPET_M + (roof.penthouse_m ?? 0) + 2.5;
  }
}

function walls(
  builder: Builder,
  ring: [number, number][],
  bottom: number,
  top: number,
  look: Look,
) {
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!;
    const b = ring[(i + 1) % ring.length]!;
    const { color, meta } = look(a, b);
    builder.wallQuad(a, b, bottom, top, color, meta);
  }
}

function hippedRoof(
  builder: Builder,
  roof: Extract<Roof, { shape: 'hipped' }>,
  eave: number,
  color: Color,
  meta: BuildingMeta,
) {
  const [c0, c1, c2, c3] = roof.obb as [
    [number, number],
    [number, number],
    [number, number],
    [number, number],
  ];
  const cx = (c0[0] + c1[0] + c2[0] + c3[0]) / 4;
  const cy = (c0[1] + c1[1] + c2[1] + c3[1]) / 4;
  const longLen = Math.hypot(c1[0] - c0[0], c1[1] - c0[1]);
  const shortLen = Math.hypot(c2[0] - c1[0], c2[1] - c1[1]);
  if (longLen < 1 || shortLen < 1) return false;
  const ax = (c1[0] - c0[0]) / longLen;
  const ay = (c1[1] - c0[1]) / longLen;
  const bx = (c2[0] - c1[0]) / shortLen;
  const by = (c2[1] - c1[1]) / shortLen;
  const L = longLen / 2 + roof.overhang;
  const W = shortLen / 2 + roof.overhang;
  const ridgeHalf = Math.max(0, L - W);
  const low = eave - 0.12;
  const high = eave + roof.rise;
  const at = (s: number, t: number, up: number): [number, number, number] => [
    cx + ax * s + bx * t,
    cy + ay * s + by * t,
    up,
  ];
  const e0 = at(-L, -W, low);
  const e1 = at(L, -W, low);
  const e2 = at(L, W, low);
  const e3 = at(-L, W, low);
  const r0 = at(-ridgeHalf, 0, high);
  const r1 = at(ridgeHalf, 0, high);
  // Winding: counter-clockwise seen from outside (above the slope).
  const flip = ax * by - ay * bx < 0;
  const tri = (
    a: [number, number, number],
    b: [number, number, number],
    c: [number, number, number],
  ) =>
    flip
      ? builder.triangle(a, c, b, color, meta)
      : builder.triangle(a, b, c, color, meta);
  tri(e0, e1, r1);
  tri(e0, r1, r0);
  tri(e2, e3, r0);
  tri(e2, r0, r1);
  tri(e1, e2, r1);
  tri(e3, e0, r0);
  // Soffit, so low views never see through the eaves.
  const soffit: [number, number][] = [e0, e1, e2, e3].map(([x, y]) => [x, y]);
  builder.cap(
    signedArea(soffit) < 0 ? soffit.reverse() : soffit,
    [],
    low,
    color,
    meta,
    false,
  );
  return true;
}

function barrelRoof(
  builder: Builder,
  roof: Extract<Roof, { shape: 'barrel' }>,
  eave: number,
  color: Color,
  meta: BuildingMeta,
) {
  const [c0, c1, c2] = roof.obb as [
    [number, number],
    [number, number],
    [number, number],
  ];
  const longLen = Math.hypot(c1[0] - c0[0], c1[1] - c0[1]);
  const shortLen = Math.hypot(c2[0] - c1[0], c2[1] - c1[1]);
  const ax = (c1[0] - c0[0]) / longLen;
  const ay = (c1[1] - c0[1]) / longLen;
  const bx = (c2[0] - c1[0]) / shortLen;
  const by = (c2[1] - c1[1]) / shortLen;
  const segments = 12;
  const flip = ax * by - ay * bx < 0;
  const arc = (k: number): [number, number] => {
    const t = (k / segments) * 2 - 1; // -1..1 across the span
    return [t * (shortLen / 2), roof.rise * (1 - t * t)];
  };
  const point = (s: number, k: number): [number, number, number] => {
    const [t, h] = arc(k);
    return [
      c0[0] + ax * s + bx * (t + shortLen / 2),
      c0[1] + ay * s + by * (t + shortLen / 2),
      eave + h,
    ];
  };
  const tri = (
    a: [number, number, number],
    b: [number, number, number],
    c: [number, number, number],
  ) =>
    flip
      ? builder.triangle(a, c, b, color, meta)
      : builder.triangle(a, b, c, color, meta);
  for (let k = 0; k < segments; k++) {
    const a = point(0, k);
    const b = point(longLen, k);
    const c = point(longLen, k + 1);
    const d = point(0, k + 1);
    tri(a, b, c);
    tri(a, c, d);
  }
  // Gable ends: fans from the middle of each eave line.
  for (const [s, reverse] of [
    [0, true],
    [longLen, false],
  ] as const) {
    const base = point(s, segments / 2);
    const mid: [number, number, number] = [base[0], base[1], eave];
    for (let k = 0; k < segments; k++) {
      const a = point(s, k);
      const b = point(s, k + 1);
      if (reverse) tri(mid, b, a);
      else tri(mid, a, b);
    }
  }
}

function minaret(
  builder: Builder,
  at: [number, number],
  height: number,
  meta: BuildingMeta,
) {
  const shaft = height * 0.74;
  builder.cylinder(at, 1.5, 1.5, 0, 3, 12, STONE, meta);
  builder.cylinder(at, 1.25, 1.15, 3, shaft, 12, STONE, meta);
  // Balcony (şerefe) and its parapet.
  builder.cylinder(at, 1.15, 2.0, shaft, shaft + 0.7, 12, STONE, meta);
  builder.cylinder(at, 2.0, 2.0, shaft + 0.7, shaft + 1.6, 12, STONE, meta);
  builder.cylinder(at, 1.0, 1.0, shaft + 1.6, height * 0.88, 12, STONE, meta);
  // Lead-clad spire (külah) with a finial.
  builder.cylinder(at, 1.15, 0, height * 0.88, height, 12, LEAD, meta, false);
}

function roofFixtures(
  builder: Builder,
  b: Building,
  roof: Extract<Roof, { shape: 'flat' }>,
  top: number,
  seed: number,
  meta: BuildingMeta,
) {
  const count = roof.units ?? 0;
  if (count === 0) return;
  const ring = roof.parapet ?? openRing(b.outline);
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of ring) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  // Fixtures follow the longest edge, as real roofs do.
  let angle = 0;
  let longest = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i]!;
    const [x2, y2] = ring[(i + 1) % ring.length]!;
    const len = Math.hypot(x2 - x1, y2 - y1);
    if (len > longest) {
      longest = len;
      angle = Math.atan2(y2 - y1, x2 - x1);
    }
  }
  const fixture = { ...meta, style: STYLE_INDEX.fixture, storey: 0 };
  let s = seed * 9301 + 49297;
  const random = () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
  let placed = 0;
  for (let attempt = 0; attempt < count * 8 && placed < count; attempt++) {
    const p: [number, number] = [
      minX + (maxX - minX) * (0.15 + random() * 0.7),
      minY + (maxY - minY) * (0.15 + random() * 0.7),
    ];
    if (!inside(p, ring)) continue;
    placed++;
    if (roof.unit_kind === 'solar') {
      // Water heater: a tilted collector facing south and its tank.
      builder.box(p, [2.0, 1.1, 0.5], angle, top, SOLAR_PANEL, fixture);
      builder.box(
        [p[0] + Math.sin(angle) * 0.9, p[1] - Math.cos(angle) * 0.9],
        [1.8, 0.55, 0.55],
        angle,
        top + 0.6,
        TANK,
        fixture,
      );
    } else {
      const w = 1.6 + random() * 2.6;
      const d = 1.4 + random() * 2.0;
      builder.box(p, [w, d, 1.1 + random() * 1.0], angle, top, HVAC, fixture);
    }
  }
}

/** The recipe texture of a geometry from `buildMassing`, if any block has one. */
export function massingRecipes(
  geometry: BufferGeometry,
): DataTexture | undefined {
  return geometry.userData.facadeRecipes as DataTexture | undefined;
}

/** Build the merged, styled geometry of ``buildings``. */
export function buildMassing(
  buildings: Building[],
): BufferGeometry | undefined {
  const builder = new Builder();
  const recipes = new RecipeTable();
  const origin = introOrigin(buildings);
  for (const b of buildings) {
    const ring = ccw(b.outline);
    if (ring.length < 3) continue;
    const style: BuildingStyle = b.style ?? (b.campus ? 'campus' : 'apartment');
    const seed = seedOf(b.id);
    const facade = b.facade;
    const styled = metaOf(b, style, seed, origin);
    const meta = facade
      ? recipeMeta(b, facade, styled, recipes.slot(facade))
      : styled;
    const palette = palettes[style];
    const wall = facade
      ? new Color(facade.wall)
      : varied(new Color(pick(palette.walls, seed)), seed);
    const look = facade ? recipeLook(facade, wall, meta) : plain(wall, meta);
    // Surveyed roof colour first, then the satellite's, then the style's.
    const roof = b.roof ?? { shape: 'flat' };
    const sampledRoof = facade?.roof
      ? new Color(facade.roof)
      : b.roof_colour
        ? new Color(b.roof_colour)
        : undefined;
    const top = b.height_m;
    const bottom = b.base_m ?? 0;
    if (facade) buildFeatures(builder, ring, facade, meta);

    if (style === 'canopy') {
      walls(builder, ring, bottom, top, plain(wall, { ...meta, storey: 0 }));
      builder.cap(
        ring,
        [],
        top,
        new Color(facade?.roof ?? pick(palette.roofs, seed)),
        meta,
      );
      builder.cap(ring, [], bottom, wall, meta, false);
      continue;
    }

    if (roof.shape === 'hipped') {
      walls(builder, ring, 0, top, look);
      const tile =
        sampledRoof ?? new Color(pick(TILE_ROOFS, (seed * 7.31) % 1));
      if (!hippedRoof(builder, roof, top, tile, meta))
        builder.cap(ring, [], top, tile, meta);
      continue;
    }

    if (roof.shape === 'barrel') {
      walls(builder, ring, 0, top, look);
      const vault = new Color(facade?.roof ?? pick(palette.roofs, seed));
      builder.cap(ring, [], top, vault, meta);
      barrelRoof(builder, roof, top, vault, meta);
      continue;
    }

    if (roof.shape === 'dome') {
      walls(builder, ring, 0, top, look);
      builder.cap(ring, [], top, STONE, meta);
      const plainMeta = { ...meta, storey: 0 };
      // Drum, dome and a small lantern.
      builder.cylinder(
        roof.centre,
        roof.radius,
        roof.radius,
        top,
        top + 1.4,
        24,
        STONE,
        plainMeta,
      );
      builder.dome(roof.centre, roof.radius, top + 1.4, LEAD, plainMeta);
      const crown = top + 1.4 + roof.radius * 0.92;
      builder.cylinder(
        roof.centre,
        0.35,
        0,
        crown - 0.1,
        crown + 1.4,
        8,
        LEAD,
        plainMeta,
        false,
      );
      minaret(builder, roof.minaret, roof.minaret_m, plainMeta);
      continue;
    }

    // Flat roof, with a parapet when it has room for one.
    const roofColor = sampledRoof ?? new Color(pick(palette.roofs, seed));
    if (roof.parapet && roof.parapet.length >= 3) {
      const inner = ccw(roof.parapet);
      walls(builder, ring, 0, top + PARAPET_M, look);
      builder.cap(inner, [], top, roofColor, meta);
      // Inner face of the parapet looks into the roof: reverse the ring.
      const reversed = [...inner].reverse();
      walls(
        builder,
        reversed,
        top,
        top + PARAPET_M,
        plain(roofColor, { ...meta, storey: 0 }),
      );
      // Coping: the recipe's trim (white stone), else the wall colour.
      const coping = facade ? new Color(facade.trim) : wall;
      builder.cap(ring, [inner], top + PARAPET_M, coping, meta);
    } else {
      walls(builder, ring, 0, top, look);
      builder.cap(ring, [], top, roofColor, meta);
    }
    if (roof.penthouse && roof.penthouse.length >= 3) {
      // Set-back top floor (çekme kat): one more storey of windows.
      const upper = ccw(roof.penthouse);
      const height = roof.penthouse_m ?? 2.9;
      const storeys = meta.storeys + 1;
      const penthouse: Look = (a, b) => {
        const side = look(a, b);
        return { color: side.color, meta: { ...side.meta, storeys } };
      };
      walls(builder, upper, top, top + height, penthouse);
      builder.cap(upper, [], top + height, roofColor, meta);
      roofFixtures(
        builder,
        b,
        { ...roof, parapet: upper },
        top + height,
        seed,
        meta,
      );
      continue;
    }
    roofFixtures(builder, b, roof, top, seed, meta);
  }
  const geometry = builder.build();
  if (geometry) geometry.userData.facadeRecipes = recipes.texture();
  return geometry;
}
