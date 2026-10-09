import type { CampusGraph } from './types';

/**
 * The walking graph's connected parts. The campus is the largest; a smaller
 * part is an island no walk reaches yet (the dormitory, ~600 m off campus,
 * whose street walk is not on the map).
 */
export interface WalkNetwork {
  partOf: ReadonlyMap<string, number>;
  /** The campus: the part with the most nodes. */
  main: number;
}

const networks = new WeakMap<CampusGraph, WalkNetwork>();

/** Parts by union-find over the edges, either way (a one-way edge still joins). */
export function walkNetworkOf(
  graph: Pick<CampusGraph, 'nodes' | 'edges'>,
): WalkNetwork {
  const cached = networks.get(graph as CampusGraph);
  if (cached) return cached;

  const parent = new Map<string, string>();
  for (const node of graph.nodes) parent.set(node.id, node.id);
  const find = (id: string): string => {
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root)!;
    // Path compression keeps the next look-ups short.
    while (parent.get(id) !== root) {
      const next = parent.get(id)!;
      parent.set(id, root);
      id = next;
    }
    return root;
  };
  for (const edge of graph.edges) {
    if (!parent.has(edge.source) || !parent.has(edge.target)) continue;
    const a = find(edge.source);
    const b = find(edge.target);
    if (a !== b) parent.set(a, b);
  }

  const index = new Map<string, number>();
  const sizes: number[] = [];
  const partOf = new Map<string, number>();
  for (const node of graph.nodes) {
    const root = find(node.id);
    let part = index.get(root);
    if (part === undefined) {
      part = sizes.length;
      index.set(root, part);
      sizes.push(0);
    }
    sizes[part] = (sizes[part] ?? 0) + 1;
    partOf.set(node.id, part);
  }
  const main = sizes.indexOf(Math.max(...sizes));
  const network = { partOf, main };
  networks.set(graph as CampusGraph, network);
  return network;
}

/** The parts a place's nodes lie in (unknown nodes are left out). */
function partsOf(
  network: WalkNetwork,
  nodeIds: readonly string[],
): Set<number> {
  const parts = new Set<number>();
  for (const id of nodeIds) {
    const part = network.partOf.get(id);
    if (part !== undefined) parts.add(part);
  }
  return parts;
}

/**
 * Whether a place can be walked to from the campus. A place the graph does
 * not know counts as reachable: the API has the last word.
 */
export function onMainNetwork(
  network: WalkNetwork,
  nodeIds: readonly string[],
): boolean {
  const parts = partsOf(network, nodeIds);
  return parts.size === 0 || parts.has(network.main);
}

/**
 * The end no walk from the other one reaches, or undefined when they share a
 * part (or the graph does not know one of them). The end off the campus is
 * the one to name; between two islands, the destination.
 */
export function detachedEnd(
  network: WalkNetwork,
  source: readonly string[],
  target: readonly string[],
): 'source' | 'target' | undefined {
  const from = partsOf(network, source);
  const to = partsOf(network, target);
  if (from.size === 0 || to.size === 0) return undefined;
  for (const part of from) if (to.has(part)) return undefined;
  return to.has(network.main) ? 'source' : 'target';
}
