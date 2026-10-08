import { describe, expect, it } from 'vitest';

import type {
  CampusGraph,
  GraphEdge,
  GraphNode,
} from '@/features/campus/types';

import {
  gapDoors,
  mapNodeId,
  routeMapIds,
  routeMatchesGraph,
  routeParts,
  shownFloor,
  spellsOtherFloor,
  viewYaw,
  whereText,
} from './indoor';

const node = (
  id: string,
  east: number,
  north: number,
  extra: Partial<GraphNode> = {},
): GraphNode => ({
  id,
  kind: 'outdoor',
  lat: 0,
  lng: 0,
  alt_m: 1.6,
  enu: [east, north, 1.6],
  heading_deg: 0,
  label: { tr: id, en: id },
  area: { tr: '', en: '' },
  building: null,
  ...extra,
});

const edge = (
  source: string,
  target: string,
  extra: Partial<GraphEdge> = {},
): GraphEdge => ({
  id: `${source}|${target}`,
  source,
  target,
  kind: 'indoor',
  length_m: 12,
  ...extra,
});

// gate -> door (measured), then a corridor and a lab standing at the door.
const gate = node('gate', 0, 0);
const door = node('door', 0, 20, { kind: 'entrance', floor: 0 });
const hall = node('hall', 0, 20, { kind: 'indoor', anchor: 'door', floor: -1 });
const lab = node('lab', 0, 20, { kind: 'indoor', anchor: 'door', floor: -1 });

function graphOf(edges: GraphEdge[]): CampusGraph {
  const nodes = [gate, door, hall, lab];
  return {
    nodes,
    edges,
    byId: new Map(nodes.map((n) => [n.id, n])),
    edgeById: new Map(edges.map((e) => [e.id, e])),
  };
}

describe('routeParts', () => {
  // gate -> door -> (hall, lab inside) ; door2 and far are past a passage.
  const door2 = node('door2', 60, 20, { kind: 'entrance', floor: 0 });
  const far = node('far', 80, 20);
  const graph = (passage: boolean): CampusGraph => {
    const g = graphOf([
      edge('door', 'gate', { kind: 'outdoor' }),
      edge('door', 'hall'),
      edge('hall', 'lab'),
      edge('door', 'door2', { kind: 'entrance', passage }),
      edge('door2', 'far', { kind: 'outdoor' }),
    ]);
    for (const n of [door2, far]) g.byId.set(n.id, n);
    return g;
  };

  it('draws only measured nodes joined by walks outside', () => {
    const parts = routeParts([gate, door, hall, lab], graph(false));
    expect(parts.map((p) => p.map((n) => n.id))).toEqual([['gate', 'door']]);
  });

  it('breaks the line at a passage through a building', () => {
    const route = [gate, door, door2, far];
    expect(
      routeParts(route, graph(true)).map((p) => p.map((n) => n.id)),
    ).toEqual([
      ['gate', 'door'],
      ['door2', 'far'],
    ]);
    expect(
      routeParts(route, graph(false)).map((p) => p.map((n) => n.id)),
    ).toEqual([['gate', 'door', 'door2', 'far']]);
  });

  it('pins a door at each end of a gap, not under the route pins', () => {
    const route = [gate, door, door2, far];
    const doors = gapDoors(routeParts(route, graph(true)));
    expect(doors.map((n) => n.id)).toEqual(['door', 'door2']);
    // Into a room: the door is the destination pin's place already.
    const inside = [gate, door, hall, lab];
    expect(gapDoors(routeParts(inside, graph(false)))).toEqual([]);
  });
});

describe('routeMatchesGraph', () => {
  const graph = graphOf([
    edge('door', 'gate', { kind: 'outdoor' }),
    edge('door', 'hall'),
  ]);

  it('accepts a route over the graph’s own nodes and edges', () => {
    expect(routeMatchesGraph(['gate', 'door', 'hall'], graph)).toBe(true);
  });

  it('rejects a hop the graph has no edge for (a newer graph)', () => {
    expect(routeMatchesGraph(['gate', 'hall'], graph)).toBe(false);
  });

  it('rejects a node the graph does not have', () => {
    expect(routeMatchesGraph(['gate', 'door', 'annex'], graph)).toBe(false);
  });
});

describe('routeMapIds', () => {
  it('frames indoor spots on their entrance, without repeats', () => {
    expect(routeMapIds([gate, door, hall, lab])).toEqual(['gate', 'door']);
    expect(routeMapIds([hall, lab])).toEqual(['door']);
  });
});

describe('mapNodeId', () => {
  it('puts indoor spots on their entrance', () => {
    expect(mapNodeId(lab)).toBe('door');
    expect(mapNodeId(gate)).toBe('gate');
  });
});

describe('viewYaw', () => {
  it('faces the tour hotspot towards the next indoor spot', () => {
    // hall is the source of hall|lab: its yaw towards lab is 90 degrees.
    const graph = graphOf([edge('hall', 'lab', { source_yaw_deg: 90 })]);
    expect(viewYaw(graph, hall, lab)).toBeCloseTo(Math.PI / 2);
  });

  it('reads the target end of an edge from the other side', () => {
    const graph = graphOf([edge('hall', 'lab', { target_yaw_deg: 180 })]);
    expect(viewYaw(graph, lab, hall)).toBeCloseTo(Math.PI);
  });

  it('keeps walking into the door when the door has no hotspot', () => {
    // gate -> door heads north; the door's front face points north.
    const graph = graphOf([edge('door', 'hall'), edge('door', 'gate')]);
    expect(viewYaw(graph, door, hall, gate)).toBeCloseTo(0);
    const east = { ...door, heading_deg: 90 };
    expect(viewYaw(graph, east, hall, gate)).toBeCloseTo((3 * Math.PI) / 2);
  });

  it('looks on from the way in on arrival', () => {
    const graph = graphOf([edge('hall', 'lab', { target_yaw_deg: 10 })]);
    // At lab, the hotspot back to hall is at 10 degrees: look the other way.
    expect(viewYaw(graph, lab, undefined, hall)).toBeCloseTo(
      (190 * Math.PI) / 180,
    );
  });

  it('falls back to the front face indoors', () => {
    expect(viewYaw(graphOf([]), hall, lab)).toBe(0);
  });

  it('uses positions between measured nodes', () => {
    const graph = graphOf([edge('door', 'gate')]);
    expect(viewYaw(graph, gate, door)).toBeCloseTo(0);
  });
});

describe('whereText', () => {
  it('names the block and the floor', () => {
    expect(whereText({ building: 'M', floor: -1 }, 'tr')).toBe(
      'M Blok · −1. kat',
    );
    expect(whereText({ building: 'M', floor: 0 }, 'en')).toBe(
      'M Block · ground floor',
    );
    expect(whereText({ floor: 3 }, 'en')).toBe('floor 3');
    expect(whereText({ building: null, floor: null }, 'tr')).toBeUndefined();
  });
});

describe('spellsOtherFloor', () => {
  it('catches a label that writes the floor with the other sign', () => {
    expect(spellsOtherFloor('T Blok -2.Kat', 2)).toBe(true);
    expect(spellsOtherFloor('T Blok -2.Kat', -2)).toBe(false);
    expect(spellsOtherFloor('M Blok-4.Kat Koridor', 4)).toBe(true);
    expect(spellsOtherFloor('T Blok 2.Kat', -2)).toBe(true);
    expect(spellsOtherFloor('Sınıf - 2', 2)).toBe(false);
  });

  it('never puts a "−2.Kat" label next to a "2. kat" badge', () => {
    expect(shownFloor(2, 'T Blok -2.Kat')).toBeUndefined();
    expect(shownFloor(-2, 'T Blok -2.Kat')).toBe(-2);
    expect(whereText({ building: 'T', floor: 2 }, 'tr', 'T Blok -2.Kat')).toBe(
      'T Blok',
    );
  });
});
