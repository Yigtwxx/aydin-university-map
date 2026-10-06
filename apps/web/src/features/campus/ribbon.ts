import { BufferGeometry, Float32BufferAttribute } from 'three';

import { enuToWorld } from './coords';

export interface RibbonLine {
  /** Polyline in local metres [east, north]. */
  points: [number, number][];
  width: number;
}

/** Miters longer than this many half-widths are clamped (sharp corners). */
const MITER_LIMIT = 2.5;

/**
 * Flat strips along polylines, merged into one geometry lying at `height`.
 *
 * - `uv.x` is the distance along the line in metres (for dashes, chevrons and
 *   draw-on animation), `uv.y` runs 0 → 1 from the left edge to the right.
 * - Corners use clamped miter joins, so a strip keeps its width through turns.
 * - `aCenter` / `aOffset` (centre point and unit half-width offset, world
 *   space) let a vertex shader rescale the width at draw time, e.g. to keep
 *   the route a minimum number of pixels wide when zoomed out.
 */
export function ribbonGeometry(
  lines: RibbonLine[],
  height = 0,
): BufferGeometry | undefined {
  const positions: number[] = [];
  const centers: number[] = [];
  const offsets: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];

  for (const { points: raw, width } of lines) {
    const points = dedupe(raw);
    if (points.length < 2 || width <= 0) continue;
    const half = width / 2;
    const base = positions.length / 3;
    let along = 0;
    for (let i = 0; i < points.length; i++) {
      const [x, y] = points[i]!;
      if (i > 0) {
        const [px, py] = points[i - 1]!;
        along += Math.hypot(x - px, y - py);
      }
      const [nx, ny, scale] = miter(points, i);
      const unit = Math.min(scale, MITER_LIMIT);
      const offset = half * unit;
      positions.push(...enuToWorld(x + nx * offset, y + ny * offset, height));
      positions.push(...enuToWorld(x - nx * offset, y - ny * offset, height));
      const center = enuToWorld(x, y, height);
      centers.push(...center, ...center);
      offsets.push(
        ...enuToWorld(nx * unit, ny * unit),
        ...enuToWorld(-nx * unit, -ny * unit),
      );
      uvs.push(along, 0, along, 1);
      if (i > 0) {
        const a = base + (i - 1) * 2;
        // Two triangles per segment, wound counter-clockwise seen from above.
        indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
      }
    }
  }
  if (indices.length === 0) return undefined;
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new Float32BufferAttribute(uvs, 2));
  geometry.setAttribute('aCenter', new Float32BufferAttribute(centers, 3));
  geometry.setAttribute('aOffset', new Float32BufferAttribute(offsets, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

/** Total polyline length in metres. */
export function lineLength(points: [number, number][]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const [ax, ay] = points[i - 1]!;
    const [bx, by] = points[i]!;
    total += Math.hypot(bx - ax, by - ay);
  }
  return total;
}

function dedupe(points: [number, number][]): [number, number][] {
  const out: [number, number][] = [];
  for (const p of points) {
    const last = out[out.length - 1];
    if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 1e-3) out.push(p);
  }
  return out;
}

/** Unit left-normal at vertex i and the miter length factor (≥ 1). */
function miter(
  points: [number, number][],
  i: number,
): [number, number, number] {
  const prev = points[i - 1];
  const here = points[i]!;
  const next = points[i + 1];
  const left = (a: [number, number], b: [number, number]) => {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    return [-dy / len, dx / len] as const;
  };
  if (!prev) {
    const [x, y] = left(here, next!);
    return [x, y, 1];
  }
  if (!next) {
    const [x, y] = left(prev, here);
    return [x, y, 1];
  }
  const [ax, ay] = left(prev, here);
  const [bx, by] = left(here, next);
  const mx = ax + bx;
  const my = ay + by;
  const len = Math.hypot(mx, my);
  // A full reversal has no defined miter; fall back to the incoming normal.
  if (len < 1e-6) return [ax, ay, 1];
  const ux = mx / len;
  const uy = my / len;
  const cos = ux * ax + uy * ay;
  return [ux, uy, 1 / Math.max(cos, 1e-3)];
}
