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
}

export interface CampusGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  byId: Map<string, GraphNode>;
}

export interface Building {
  id: string;
  name: string | null;
  campus: boolean;
  height_m: number;
  /** Closed ring in local metres [east, north]. */
  outline: [number, number][];
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
  return { nodes, edges, byId: new Map(nodes.map((n) => [n.id, n])) };
}
