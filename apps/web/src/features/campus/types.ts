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
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  length_m: number;
  /** Walking line source -> target [east, north] when it bends round buildings. */
  path_enu?: [number, number][] | null;
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

export interface Building {
  id: string;
  name: string | null;
  campus: boolean;
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
  /** Tree positions in local metres [east, north]. */
  trees: [number, number][];
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
