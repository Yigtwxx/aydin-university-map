/**
 * Street furniture and the ground's level changes (`furniture.json`), mirroring
 * `amap_contracts.furniture`. Coordinates are local ENU metres [east, north];
 * heights are metres above the street datum (z = 0, the map's ground plane).
 */

type Point = [number, number];

/** How a terrace meets the ground around it. */
export type TerraceEdge = 'wall' | 'slope' | 'kerb';

/** Which sides of a flight carry a handrail, seen walking up from the foot. */
export type RailSide = 'none' | 'left' | 'right' | 'both';

export type ItemKind =
  | 'bench'
  | 'table'
  | 'chair'
  | 'umbrella'
  | 'planter'
  | 'bollard'
  | 'bin'
  | 'lamp'
  | 'bike_rack'
  | 'flagpole'
  | 'booth'
  | 'kiosk'
  | 'emblem'
  | 'letters'
  | 'topiary'
  | 'statue'
  | 'sign'
  | 'stand'
  | 'hedge';

/** A level area raised above (or sunk below) the street datum. */
export interface Terrace {
  id: string;
  outline: Point[];
  z_m: number;
  edge: TerraceEdge;
  /** Width of a 'slope' edge's bank (m); null sizes it from the climb. */
  bank_m?: number | null;
}

/** A flight's drawn outline when it is not a rectangle (left walking up). */
export interface StairCorners {
  foot_left: Point;
  foot_right: Point;
  top_left: Point;
  top_right: Point;
}

/** A straight flight: centreline from its foot to its top. */
export interface Stairs {
  id: string;
  foot: Point;
  top: Point;
  width_m: number;
  /** Number of risers. */
  steps: number;
  /** Ground height at the foot. */
  base_z: number;
  /** Height climbed in total. */
  rise_m: number;
  railings: RailSide;
  /** Tiers cut to meet their neighbours; foot/top stay the walking line. */
  corners?: StairCorners | null;
}

export interface Ramp {
  id: string;
  foot: Point;
  top: Point;
  width_m: number;
  base_z: number;
  rise_m: number;
  railings: RailSide;
}

/** A free-standing rail (terrace edges, lane walls). */
/** steel: posts and rails; fence: the campus boundary (brick and iron). */
export type RailingStyle = 'steel' | 'fence';

export interface Railing {
  id: string;
  line: Point[];
  height_m: number;
  base_z: number;
  style?: RailingStyle;
}

/**
 * One placed object. `heading_deg` is the compass bearing its front faces
 * (where someone sitting on a bench looks); `length_m` runs across that, along
 * the object's long side (a bench, a planter box, a row of bike hoops).
 * `base_z` 0 means "on the ground here" (the terrain's height at `at`).
 */
export interface FurnitureItem {
  id: string;
  kind: ItemKind;
  at: Point;
  heading_deg: number;
  length_m: number | null;
  base_z: number;
}

/** Café tables and chairs: an area and how many, not a layout. */
export interface SeatingGroup {
  id: string;
  outline: Point[];
  tables: number;
  seats_per_table: number;
  umbrellas: boolean;
  poi: string | null;
  base_z: number;
}

/**
 * A raised walk over lower ground (a slab on columns, a footbridge). Drawn by
 * the blocks' canopy features; here so a route on it is drawn up there.
 */
export interface Walkway {
  id: string;
  outline: Point[];
  z_m: number;
  /** Panoramas taken up on it (graph node ids). */
  spots: string[];
}

export interface Furniture {
  schema_version: number;
  terraces: Terrace[];
  stairs: Stairs[];
  ramps: Ramp[];
  railings: Railing[];
  items: FurnitureItem[];
  seating: SeatingGroup[];
  walkways: Walkway[];
}

export const EMPTY_FURNITURE: Furniture = Object.freeze({
  schema_version: 1,
  terraces: [],
  stairs: [],
  ramps: [],
  railings: [],
  items: [],
  seating: [],
  walkways: [],
}) as Furniture;

/** Defaults the contract fills in, for a file that leaves them out. */
function normalise(raw: Partial<Furniture>): Furniture {
  return {
    schema_version: raw.schema_version ?? 1,
    terraces: (raw.terraces ?? []).map((t) => ({
      ...t,
      edge: t.edge ?? 'wall',
      bank_m: t.bank_m ?? null,
    })),
    stairs: (raw.stairs ?? []).map((s) => ({
      ...s,
      base_z: s.base_z ?? 0,
      railings: s.railings ?? 'none',
      corners: s.corners ?? null,
    })),
    ramps: (raw.ramps ?? []).map((r) => ({
      ...r,
      base_z: r.base_z ?? 0,
      railings: r.railings ?? 'none',
    })),
    railings: (raw.railings ?? []).map((r) => ({
      ...r,
      height_m: r.height_m ?? 1,
      base_z: r.base_z ?? 0,
    })),
    items: (raw.items ?? []).map((i) => ({
      ...i,
      heading_deg: i.heading_deg ?? 0,
      length_m: i.length_m ?? null,
      base_z: i.base_z ?? 0,
    })),
    seating: (raw.seating ?? []).map((g) => ({
      ...g,
      seats_per_table: g.seats_per_table ?? 4,
      umbrellas: g.umbrellas ?? false,
      poi: g.poi ?? null,
      base_z: g.base_z ?? 0,
    })),
    walkways: (raw.walkways ?? []).map((w) => ({
      id: w.id,
      outline: w.outline,
      z_m: w.z_m,
      spots: w.spots ?? [],
    })),
  };
}

/**
 * Loads `furniture.json` from the asset base. The asset is optional (ADR-0011):
 * a 404 means the campus has none yet and resolves to an empty collection;
 * any other failure is an error.
 */
export async function fetchFurniture(
  baseUrl: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Furniture> {
  const response = await fetchImpl(`${baseUrl}/furniture.json`);
  if (response.status === 404) return EMPTY_FURNITURE;
  if (!response.ok) throw new Error(`furniture.json: HTTP ${response.status}`);
  return normalise((await response.json()) as Partial<Furniture>);
}
