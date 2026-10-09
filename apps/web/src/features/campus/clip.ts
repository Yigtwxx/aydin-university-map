import { BufferGeometry, Float32BufferAttribute } from 'three';

import { paveOf } from './paving';
import type { TerraceShape } from './terrain';

type XY = [number, number];

/**
 * Sutherland–Hodgman: the part of `subject` inside the convex,
 * counter-clockwise polygon `clip`.
 */
export function clipConvex(subject: XY[], clip: XY[]): XY[] {
  let output = subject;
  for (let i = 0; i < clip.length && output.length > 0; i++) {
    const [ax, ay] = clip[i]!;
    const [bx, by] = clip[(i + 1) % clip.length]!;
    const ex = bx - ax;
    const ey = by - ay;
    const side = ([px, py]: XY) => ex * (py - ay) - ey * (px - ax);
    const input = output;
    output = [];
    for (let j = 0; j < input.length; j++) {
      const p = input[j]!;
      const q = input[(j + 1) % input.length]!;
      const sp = side(p);
      const sq = side(q);
      if (sp >= 0) output.push(p);
      if (sp >= 0 !== sq >= 0) {
        const t = sp / (sp - sq);
        output.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
      }
    }
  }
  return output;
}

function area2(poly: XY[]): number {
  let sum = 0;
  for (let i = 0; i < poly.length; i++) {
    const [ax, ay] = poly[i]!;
    const [bx, by] = poly[(i + 1) % poly.length]!;
    sum += ax * by - bx * ay;
  }
  return sum;
}

interface RegionTriangle {
  tri: XY[];
  box: [number, number, number, number];
}

function boxOf(points: XY[]): [number, number, number, number] {
  let minE = Infinity;
  let minN = Infinity;
  let maxE = -Infinity;
  let maxN = -Infinity;
  for (const [e, n] of points) {
    minE = Math.min(minE, e);
    minN = Math.min(minN, n);
    maxE = Math.max(maxE, e);
    maxN = Math.max(maxN, n);
  }
  return [minE, minN, maxE, maxN];
}

const overlap = (
  a: [number, number, number, number],
  b: [number, number, number, number],
) => a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];

/**
 * The parts of a flat ground layer (three.js world positions, any height)
 * that lie on terraces, each lifted to its terrace's top plus `lift`.
 *
 * The layer itself stays at street level, where the terraces' tops hide it;
 * drawing these parts with the same material and render order puts the
 * paths and paving on the terraces without splitting the original geometry.
 * Each lifted vertex carries its terrace's paving (`paving`, see paving.ts).
 */
export function liftOntoTerraces(
  geometry: BufferGeometry,
  terraces: readonly TerraceShape[],
  lift: number,
): BufferGeometry | undefined {
  if (terraces.length === 0) return undefined;
  const regions = terraces.map((t) => {
    const tris: RegionTriangle[] = [];
    for (let i = 0; i < t.triangles.length; i += 6) {
      const tri: XY[] = [
        [t.triangles[i]!, t.triangles[i + 1]!],
        [t.triangles[i + 2]!, t.triangles[i + 3]!],
        [t.triangles[i + 4]!, t.triangles[i + 5]!],
      ];
      if (area2(tri) < 0) tri.reverse();
      tris.push({ tri, box: boxOf(tri) });
    }
    return { z: t.z + lift, box: t.bbox, tris, pave: paveOf(t.id) };
  });

  const position = geometry.getAttribute('position');
  const index = geometry.getIndex();
  const count = index ? index.count : position.count;
  const at = (k: number): XY => {
    const v = index ? index.getX(k) : k;
    // World (x, z) back to ENU (east, north).
    return [position.getX(v), -position.getZ(v)];
  };

  const out: number[] = [];
  const paving: number[] = [];
  for (let k = 0; k + 2 < count; k += 3) {
    const tri: XY[] = [at(k), at(k + 1), at(k + 2)];
    const a = area2(tri);
    if (Math.abs(a) < 1e-9) continue;
    if (a < 0) tri.reverse();
    const box = boxOf(tri);
    for (const region of regions) {
      if (!overlap(box, region.box)) continue;
      for (const piece of region.tris) {
        if (!overlap(box, piece.box)) continue;
        const poly = clipConvex(tri, piece.tri);
        if (poly.length < 3 || area2(poly) < 1e-6) continue;
        // Counter-clockwise in (east, north) faces up in the world.
        for (let i = 1; i + 1 < poly.length; i++) {
          for (const [e, n] of [poly[0]!, poly[i]!, poly[i + 1]!]) {
            out.push(e, region.z, -n);
            paving.push(region.pave);
          }
        }
      }
    }
  }
  if (out.length === 0) return undefined;
  const lifted = new BufferGeometry();
  lifted.setAttribute('position', new Float32BufferAttribute(out, 3));
  const normals = new Float32Array(out.length);
  for (let i = 1; i < normals.length; i += 3) normals[i] = 1;
  lifted.setAttribute('normal', new Float32BufferAttribute(normals, 3));
  lifted.setAttribute('paving', new Float32BufferAttribute(paving, 1));
  return lifted;
}
