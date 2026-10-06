import { bearingDeg, yawForBearing } from '@/features/campus/coords';
import type {
  CampusGraph,
  GraphEdge,
  GraphNode,
} from '@/features/campus/types';
import { formatFloor, type Locale } from '@/lib/format';

/**
 * Indoor spots come from the tour's links, not from measurements: they stand
 * at the entrance they hang off (`anchor`). The map draws only measured
 * nodes and walks outside (never passages through buildings); the 360° view
 * faces the tour's own hotspots indoors.
 */
export function isIndoorSpot(node: GraphNode | undefined): boolean {
  return Boolean(node?.anchor);
}

/** The map's node for a spot: itself, or the entrance an indoor spot hangs off. */
export function mapNodeId(node: GraphNode): string {
  return node.anchor ?? node.id;
}

/**
 * The parts of a route the map can draw, in walking order: runs of measured
 * nodes joined by walks outside. The line breaks wherever the route steps
 * onto an indoor spot (a borrowed position) or takes a passage through a
 * building; a part of one node is nothing to draw.
 */
export function routeParts(
  nodes: GraphNode[],
  graph: CampusGraph,
): GraphNode[][] {
  const parts: GraphNode[][] = [[]];
  nodes.forEach((node, i) => {
    const previous = nodes[i - 1];
    const edge = previous
      ? edgeBetween(graph, previous.id, node.id)
      : undefined;
    const joined = Boolean(edge && !edge.passage);
    if (isIndoorSpot(node) || !joined) parts.push([]);
    if (!isIndoorSpot(node)) parts[parts.length - 1]!.push(node);
  });
  return parts.filter((part) => part.length > 1);
}

/**
 * Doors at the ends of the gaps between drawn parts: where the walk goes
 * inside (or through a building) and where it comes out. The first and the
 * last drawn node carry the start and destination pins instead.
 */
export function gapDoors(parts: GraphNode[][]): GraphNode[] {
  const doors = new Map<string, GraphNode>();
  parts.forEach((part, i) => {
    const head = part[0]!;
    const tail = part[part.length - 1]!;
    if (i > 0) doors.set(head.id, head);
    if (i < parts.length - 1) doors.set(tail.id, tail);
  });
  return [...doors.values()];
}

/**
 * The map's nodes a route covers, in order, for framing it: indoor spots on
 * their entrance, repeats dropped. A route inside one building is its door.
 */
export function routeMapIds(nodes: GraphNode[]): string[] {
  const ids: string[] = [];
  for (const node of nodes) {
    const id = mapNodeId(node);
    if (ids[ids.length - 1] !== id) ids.push(id);
  }
  return ids;
}

export function edgeBetween(
  graph: CampusGraph,
  a: string,
  b: string,
): GraphEdge | undefined {
  return graph.edgeById.get(`${a}|${b}`) ?? graph.edgeById.get(`${b}|${a}`);
}

/** Yaw at `node` (degrees from its front face) towards `other`: the tour's hotspot. */
function hotspotYaw(
  graph: CampusGraph,
  node: GraphNode,
  other: GraphNode,
): number | undefined {
  const edge = edgeBetween(graph, node.id, other.id);
  if (!edge) return undefined;
  const yaw =
    edge.source === node.id ? edge.source_yaw_deg : edge.target_yaw_deg;
  return yaw ?? undefined;
}

const radians = (degrees: number) =>
  ((((degrees % 360) + 360) % 360) * Math.PI) / 180;

function measuredPair(a: GraphNode, b: GraphNode): boolean {
  return (
    !isIndoorSpot(a) &&
    !isIndoorSpot(b) &&
    (a.enu[0] !== b.enu[0] || a.enu[1] !== b.enu[1])
  );
}

/**
 * Viewer yaw (radians, clockwise from the front face) that looks the way the
 * walker goes from `node`: towards `next`, or on arrival onward from
 * `previous`. Indoors positions say nothing, so the tour's hotspot towards
 * the next spot decides; without one, the walk's last measured direction
 * (into the door); else the front face.
 */
export function viewYaw(
  graph: CampusGraph,
  node: GraphNode,
  next?: GraphNode,
  previous?: GraphNode,
): number {
  if (next) {
    const ahead = hotspotYaw(graph, node, next);
    if (ahead !== undefined) return radians(ahead);
    if (measuredPair(node, next))
      return yawForBearing(
        bearingDeg([node.enu[0], node.enu[1]], [next.enu[0], next.enu[1]]),
        node.heading_deg,
      );
  }
  if (previous) {
    const back = hotspotYaw(graph, node, previous);
    if (back !== undefined) return radians(back + 180);
    if (measuredPair(previous, node))
      return yawForBearing(
        bearingDeg(
          [previous.enu[0], previous.enu[1]],
          [node.enu[0], node.enu[1]],
        ),
        node.heading_deg,
      );
  }
  return 0;
}

/**
 * The label writes this floor's number with the other sign ("T Blok -2.Kat"
 * shown with "2. kat"): then the floor is left out and the label speaks.
 * Mirrors amap_contracts.text.spells_other_floor.
 */
export function spellsOtherFloor(label: string, floor: number): boolean {
  if (floor > 0)
    return [...label.matchAll(/[-\u2212](\d+)(?!\d)/g)].some(
      (m) => Number(m[1]) === floor,
    );
  if (floor < 0)
    return [...label.matchAll(/(?:^|\s)(\d+)\s*\.\s*(?:Kat|K\b)/gi)].some(
      (m) => Number(m[1]) === -floor,
    );
  return false;
}

/** The floor to show next to `labels`, if any (see spellsOtherFloor). */
export function shownFloor(
  floor: number | null | undefined,
  ...labels: string[]
): number | undefined {
  if (floor === null || floor === undefined) return undefined;
  return labels.some((l) => spellsOtherFloor(l, floor)) ? undefined : floor;
}

/** Where a room is, for a subtitle or a pin: "M Blok · −1. kat", "M Block · floor −1". */
export function whereText(
  spot: { building?: string | null; floor?: number | null },
  locale: Locale,
  ...labels: string[]
): string | undefined {
  const parts: string[] = [];
  if (spot.building)
    parts.push(
      locale === 'tr' ? `${spot.building} Blok` : `${spot.building} Block`,
    );
  const floor = shownFloor(spot.floor, ...labels);
  if (floor !== undefined) parts.push(formatFloor(floor, locale));
  return parts.length ? parts.join(' · ') : undefined;
}
