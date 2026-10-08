import {
  Color,
  DataTexture,
  FloatType,
  NearestFilter,
  RGBAFormat,
} from 'three';

import type { Facade, FacadeWall, GroundFloor, WindowRecipe } from './types';

/**
 * Surveyed facade recipes (amap_contracts.facade) on the GPU.
 *
 * Each recipe is one row of a float texture, RECIPE_TEXELS vec4s wide:
 *   0: bay width m, window width share, window height share, sill share
 *   1: plinth rgb (linear), 1 when the block has a plinth
 *   2: trim rgb (linear), corner pilaster width m (0 = none)
 *   3: glass rgb (linear), 0
 * Vertices pick their row with a byte attribute (aFlags.y = row + 1, 0 = no
 * recipe), so the table holds up to MAX_RECIPES blocks. What changes from one
 * side of a block to another (wall colour, window kind, ground floor) is
 * resolved on the CPU per wall and travels with the vertices.
 */

export const RECIPE_TEXELS = 4;
/** Slots fit a byte attribute; slot 0 means "no recipe". */
export const MAX_RECIPES = 255;

/** aFlags.z: what the windows above the ground floor are. */
export const WINDOW_MODE: Record<WindowRecipe, number> = {
  punched: 0,
  ribbon: 1,
  curtain: 2,
  blank: 3,
};

/**
 * aFlags.z of a feature's masonry walls (a tower): brick courses and a
 * recessed panel instead of windows. Then aMeta.w is the feature's base and
 * aWall.w its height.
 */
export const MASONRY_MODE = 4;

/** aFlags.w: what the ground floor is. */
export const GROUND_MODE: Record<GroundFloor, number> = {
  same: 0,
  glazed: 1,
  solid: 2,
  arcade: 3,
};

/**
 * Where a window starts in its storey (share from the slab): a little more
 * wall below the window than above it, as with a real sill and lintel.
 */
export function sillShare(windowHeight: number): number {
  return Math.max(0.04, (1 - windowHeight) * 0.56);
}

/** One recipe's texels (RECIPE_TEXELS x 4 floats, linear colours). */
export function packRecipe(facade: Facade): Float32Array {
  const plinth = facade.plinth ? new Color(facade.plinth) : undefined;
  const trim = new Color(facade.trim);
  const glass = new Color(facade.glass);
  return Float32Array.from([
    facade.bay_m,
    facade.window_width,
    facade.window_height,
    sillShare(facade.window_height),
    plinth?.r ?? 0,
    plinth?.g ?? 0,
    plinth?.b ?? 0,
    plinth ? 1 : 0,
    trim.r,
    trim.g,
    trim.b,
    facade.quoins_m ?? 0,
    glass.r,
    glass.g,
    glass.b,
    0,
  ]);
}

/** The recipes of one merged massing, deduplicated, ready for a texture. */
export class RecipeTable {
  private readonly rows: Float32Array[] = [];
  private readonly slots = new Map<string, number>();

  /** Slot of the recipe (1-based), or 0 once the table is full. */
  slot(facade: Facade): number {
    const row = packRecipe(facade);
    const key = Array.from(row, (x) => x.toFixed(5)).join(',');
    const known = this.slots.get(key);
    if (known !== undefined) return known;
    if (this.rows.length >= MAX_RECIPES) return 0;
    this.rows.push(row);
    this.slots.set(key, this.rows.length);
    return this.rows.length;
  }

  get size(): number {
    return this.rows.length;
  }

  /** Row-major texels, one recipe per row. */
  pack(): Float32Array {
    const data = new Float32Array(this.rows.length * RECIPE_TEXELS * 4);
    this.rows.forEach((row, i) => data.set(row, i * RECIPE_TEXELS * 4));
    return data;
  }

  /** Float texture the facade shader reads with texelFetch; none when empty. */
  texture(): DataTexture | undefined {
    if (this.rows.length === 0) return undefined;
    const texture = new DataTexture(
      this.pack(),
      RECIPE_TEXELS,
      this.rows.length,
      RGBAFormat,
      FloatType,
    );
    texture.minFilter = NearestFilter;
    texture.magFilter = NearestFilter;
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    return texture;
  }
}

/**
 * Compass bearing (degrees, 0 = north, clockwise) a wall from `a` to `b`
 * faces, for a counter-clockwise ring in (east, north).
 */
export function facingOf(a: [number, number], b: [number, number]): number {
  // Outward normal: to the right of a -> b.
  const east = b[1] - a[1];
  const north = -(b[0] - a[0]);
  const deg = (Math.atan2(east, north) * 180) / Math.PI;
  return (deg + 360) % 360;
}

/** Smallest angle between two bearings, 0..180. */
export function angularDistance(a: number, b: number): number {
  const d = Math.abs((((a - b) % 360) + 360) % 360);
  return d > 180 ? 360 - d : d;
}

/** The override for a wall facing `bearing`: the closest within tolerance. */
export function sideOf(
  facade: Facade,
  bearing: number,
): FacadeWall | undefined {
  let best: FacadeWall | undefined;
  let bestD = Infinity;
  for (const wall of facade.walls) {
    const d = angularDistance(wall.facing_deg, bearing);
    if (d <= wall.tolerance_deg && d < bestD) {
      best = wall;
      bestD = d;
    }
  }
  return best;
}

export interface Storeys {
  /** Ground floor height, m. */
  ground: number;
  /** Height of each floor above it, m. */
  storey: number;
  /** Floors above the ground floor. */
  upper: number;
}

/**
 * Fit the recipe's floors to the block: the surveyed ground floor, then
 * whole storeys up to the roof (OSM levels count the ground floor), each
 * stretched a little so no window is cut by the roof line.
 */
export function fitStoreys(
  facade: Facade,
  height: number,
  levels?: number,
): Storeys {
  const ground = Math.min(facade.ground_m, height);
  const rest = height - ground;
  let upper =
    levels !== undefined
      ? Math.max(0, Math.round(levels) - 1)
      : Math.max(0, Math.round(rest / facade.storey_m));
  // Never squeeze a storey under the contract's minimum.
  if (upper > 0 && rest / upper < 2.4) upper = Math.floor(rest / 2.4);
  const storey = upper > 0 ? rest / upper : facade.storey_m;
  return { ground, storey, upper };
}
