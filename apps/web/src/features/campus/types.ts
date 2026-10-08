/** Mirrors amap_contracts.graph (GeoJSON) and the pipeline's buildings.json. */

export type NodeKind = 'outdoor' | 'entrance' | 'indoor';
export type EdgeKind =
  'outdoor' | 'entrance' | 'indoor' | 'stairs' | 'elevator';

export interface LocalizedText {
  tr: string;
  en: string;
}

export interface GraphNode {
  id: string;
  kind: NodeKind;
  lat: number;
  lng: number;
  alt_m: number;
  /** Local metres from the campus origin: east, north, up. */
  enu: [number, number, number];
  /** Compass bearing of the panorama's front face centre. */
  heading_deg: number;
  label: LocalizedText;
  area: LocalizedText;
  building: string | null;
  /** Storey (0 = ground, negative = basement); missing in older graphs. */
  floor?: number | null;
  /**
   * Indoor spots have no measured position: they stand at this measured
   * node (the entrance they hang off). Never draw them as places of their own.
   */
  anchor?: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  length_m: number;
  /** Walking line source -> target [east, north] when it bends round buildings. */
  path_enu?: [number, number][] | null;
  /** Panorama yaw (degrees from the front face) looking along the edge, from the tour. */
  source_yaw_deg?: number | null;
  target_yaw_deg?: number | null;
  /** A walk through a building between two doors: never drawn on the map. */
  passage?: boolean;
  /** The line crosses seating or a hedge, or a wall with no flight noted. */
  crosses?: 'soft' | 'barrier' | null;
  /** 'tour': walked between two panoramas; 'inferred': added by line of sight. */
  origin?: 'tour' | 'inferred';
}

export interface CampusGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  byId: Map<string, GraphNode>;
  /** Edges keyed "source|target" (ids sorted, as the pipeline writes them). */
  edgeById: Map<string, GraphEdge>;
}

/** What a building is (pipeline: geo/building_style.py). */
export type BuildingStyle =
  | 'campus'
  | 'apartment'
  | 'house'
  | 'retail'
  | 'showroom'
  | 'office'
  | 'industrial'
  | 'hangar'
  | 'school'
  | 'dormitory'
  | 'worship'
  | 'hospital'
  | 'hotel'
  | 'sports'
  | 'canopy';

type Ring = [number, number][];

export type Roof =
  | {
      shape: 'flat';
      /** Inner ring of a parapet wall around the roof. */
      parapet?: Ring;
      /** Set-back top floor (çekme kat) outline and height. */
      penthouse?: Ring;
      penthouse_m?: number;
      units?: number;
      unit_kind?: 'solar' | 'hvac';
    }
  | {
      shape: 'hipped';
      /** Minimum rotated rectangle, long side first. */
      obb: Ring;
      rise: number;
      overhang: number;
    }
  | { shape: 'barrel'; obb: Ring; rise: number }
  | {
      shape: 'dome';
      centre: [number, number];
      radius: number;
      minaret: [number, number];
      minaret_m: number;
    };

/**
 * How a campus block looks from the outside (amap_contracts.facade). Colours
 * are sRGB hex, lengths metres; every field is filled in when present.
 */
export type WindowRecipe = 'punched' | 'ribbon' | 'curtain' | 'blank';
export type GroundFloor = 'same' | 'glazed' | 'solid' | 'arcade';
export type FeatureKind =
  'drum' | 'tower' | 'canopy' | 'portal' | 'band' | 'glass';

/** A side of the block that differs from the recipe. */
export interface FacadeWall {
  /** Compass direction the wall faces (out), degrees. */
  facing_deg: number;
  tolerance_deg: number;
  windows: WindowRecipe | null;
  wall: string | null;
  ground: GroundFloor | null;
}

/** A shape that makes the block recognisable (drum, tower, canopy...). */
export interface FacadeFeature {
  kind: FeatureKind;
  /** Centre in local metres [east, north]; null for bands. */
  at: [number, number] | null;
  width_m: number;
  depth_m: number;
  height_m: number;
  base_m: number;
  /** Compass direction the feature's front faces, degrees. */
  facing_deg: number;
  colour: string;
  accent: string | null;
}

export interface Facade {
  wall: string;
  /** Ground-floor band, if different from the wall. */
  plinth: string | null;
  trim: string;
  glass: string;
  roof: string | null;
  windows: WindowRecipe;
  /** Window spacing, m. */
  bay_m: number;
  /** Share of the bay. */
  window_width: number;
  /** Share of the storey. */
  window_height: number;
  storey_m: number;
  ground: GroundFloor;
  ground_m: number;
  /** Corner pilaster strips in the trim colour, m wide; 0 or missing = none. */
  quoins_m?: number;
  walls: FacadeWall[];
  features: FacadeFeature[];
}

export interface Building {
  id: string;
  name: string | null;
  campus: boolean;
  /** Campus block code from the registry ("A", "G-H", "KUTUPHANE"). */
  code?: string;
  /** Surveyed facade recipe; without it the block keeps its style's look. */
  facade?: Facade;
  height_m: number;
  /** Closed ring in local metres [east, north]. */
  outline: Ring;
  /** Missing in assets exported before building styles existed. */
  style?: BuildingStyle;
  levels?: number;
  roof?: Roof;
  /** Underside of a raised slab (canopies), metres above ground. */
  base_m?: number;
  /** Shops or cafés at street level. */
  shops?: boolean;
  /** Roof colour sampled from satellite imagery (#rrggbb). */
  roof_colour?: string;
}

export interface Greenery {
  areas: { kind: string; outline: [number, number][] }[];
  /**
   * Trees in local metres: [east, north] or [east, north, height_m], the
   * height being the whole tree, ground to crown top (see treeShape.ts).
   */
  trees: ([number, number] | [number, number, number])[];
}

/** OSM streets, footpaths and ground areas (pipeline: `amap export ground`). */
export interface Ground {
  ways: {
    kind: string;
    name: string | null;
    width_m: number;
    /** Polyline in local metres [east, north]. */
    line: [number, number][];
  }[];
  areas: {
    kind: 'campus' | 'pedestrian' | 'parking' | 'pitch' | 'water';
    name: string | null;
    outline: [number, number][];
  }[];
}

interface GeoFeature {
  properties: Record<string, unknown> & { feature: 'node' | 'edge' };
}

export function parseGraph(geojson: { features: GeoFeature[] }): CampusGraph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  for (const feature of geojson.features) {
    if (feature.properties.feature === 'node') {
      nodes.push(feature.properties as unknown as GraphNode);
    } else {
      edges.push(feature.properties as unknown as GraphEdge);
    }
  }
  return {
    nodes,
    edges,
    byId: new Map(nodes.map((n) => [n.id, n])),
    edgeById: new Map(edges.map((e) => [e.id, e])),
  };
}
