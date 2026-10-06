import type { GraphEdge, GraphNode } from './types';

type XY = [number, number];

/**
 * The walking line of a route in local metres [east, north]: node to node,
 * following each edge's bend around buildings (``path_enu``) where it has one.
 */
export function routePolyline(
  nodes: GraphNode[],
  edges: Map<string, GraphEdge>,
): XY[] {
  const out: XY[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]!;
    if (i === 0) {
      out.push([node.enu[0], node.enu[1]]);
      continue;
    }
    const prev = nodes[i - 1]!;
    const edge =
      edges.get(`${prev.id}|${node.id}`) ?? edges.get(`${node.id}|${prev.id}`);
    const path = edge?.path_enu;
    if (path && path.length > 2) {
      const forward = edge.source === prev.id;
      const inner = path.slice(1, -1);
      out.push(...(forward ? inner : [...inner].reverse()));
    }
    out.push([node.enu[0], node.enu[1]]);
  }
  return out;
}

function distanceToSegment(p: XY, a: XY, b: XY): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t =
    len2 === 0
      ? 0
      : Math.max(
          0,
          Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2),
        );
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** Douglas-Peucker: drop vertices within ``tolerance`` metres of the line. */
export function simplify(points: XY[], tolerance: number): XY[] {
  if (points.length < 3) return points;
  const keep = new Uint8Array(points.length);
  keep[0] = 1;
  keep[points.length - 1] = 1;
  const stack: [number, number][] = [[0, points.length - 1]];
  while (stack.length) {
    const [start, end] = stack.pop()!;
    let worst = -1;
    let index = -1;
    for (let i = start + 1; i < end; i++) {
      const d = distanceToSegment(points[i]!, points[start]!, points[end]!);
      if (d > worst) {
        worst = d;
        index = i;
      }
    }
    if (worst > tolerance && index > 0) {
      keep[index] = 1;
      stack.push([start, index], [index, end]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

/** Chaikin corner cutting: rounds turns, keeps both ends in place. */
export function chaikin(points: XY[], iterations: number): XY[] {
  let line = points;
  for (let k = 0; k < iterations && line.length > 2; k++) {
    const next: XY[] = [line[0]!];
    for (let i = 0; i < line.length - 1; i++) {
      const [ax, ay] = line[i]!;
      const [bx, by] = line[i + 1]!;
      // Keep the end segments' outer halves so the line meets its pins.
      if (i > 0) next.push([ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25]);
      if (i < line.length - 2)
        next.push([ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75]);
    }
    next.push(line[line.length - 1]!);
    line = next;
  }
  return line;
}

/** Evenly spaced points every ``step`` metres (ends kept). */
export function resample(points: XY[], step: number): XY[] {
  if (points.length < 2) return points;
  const out: XY[] = [points[0]!];
  let carry = 0;
  for (let i = 1; i < points.length; i++) {
    const [ax, ay] = points[i - 1]!;
    const [bx, by] = points[i]!;
    const len = Math.hypot(bx - ax, by - ay);
    let t = step - carry;
    while (t < len) {
      out.push([ax + ((bx - ax) * t) / len, ay + ((by - ay) * t) / len]);
      t += step;
    }
    carry = len - (t - step);
  }
  const last = points[points.length - 1]!;
  const tail = out[out.length - 1]!;
  if (Math.hypot(last[0] - tail[0], last[1] - tail[1]) > step * 0.3)
    out.push(last);
  else out[out.length - 1] = last;
  return out;
}

/**
 * The smooth, evenly sampled line the route ribbon is drawn along. Node
 * jitter is simplified away first; resampling every 2 m before rounding keeps
 * each corner cut within ~0.35 m, well inside the 1.2 m clearance detours
 * keep from walls.
 */
export function smoothRoute(points: XY[]): XY[] {
  return resample(chaikin(resample(simplify(points, 0.6), 2), 3), 0.75);
}
