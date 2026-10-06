import {
  BufferGeometry,
  type Color,
  ExtrudeGeometry,
  Float32BufferAttribute,
  Shape,
  Vector2,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type { Building } from './types';

/** Drop the closing vertex of an OSM ring (first == last). */
export function openRing(ring: [number, number][]): [number, number][] {
  if (ring.length > 1) {
    const [fx, fy] = ring[0]!;
    const [lx, ly] = ring[ring.length - 1]!;
    if (fx === lx && fy === ly) return ring.slice(0, -1);
  }
  return ring;
}

/**
 * Extrude footprints (local ENU metres) into one merged geometry.
 * The shape lives in (east, north); rotateX(-90°) maps it to three's
 * (x east, y up, z south) and the extrusion depth becomes height.
 */
export function extrudeBuildings(
  buildings: Building[],
): BufferGeometry | undefined {
  const parts: BufferGeometry[] = [];
  for (const building of buildings) {
    const ring = openRing(building.outline);
    if (ring.length < 3) continue;
    const shape = new Shape(
      ring.map(([east, north]) => new Vector2(east, north)),
    );
    const geometry = new ExtrudeGeometry(shape, {
      depth: building.height_m,
      bevelEnabled: false,
    });
    geometry.rotateX(-Math.PI / 2);
    parts.push(geometry);
  }
  if (parts.length === 0) return undefined;
  const merged = mergeGeometries(parts, false);
  for (const part of parts) part.dispose();
  merged.computeVertexNormals();
  return merged;
}

/**
 * Paint walls and roofs with vertex colours: faces pointing up are roofs.
 * Keeps one merged mesh (one draw call) while reading as real buildings.
 */
export function paintWallsAndRoofs(
  geometry: BufferGeometry,
  wall: Color,
  roof: Color,
): void {
  const normals = geometry.getAttribute('normal');
  const colors = new Float32Array(normals.count * 3);
  for (let i = 0; i < normals.count; i++) {
    const c = normals.getY(i) > 0.5 ? roof : wall;
    colors[i * 3] = c.r;
    colors[i * 3 + 1] = c.g;
    colors[i * 3 + 2] = c.b;
  }
  geometry.setAttribute('color', new Float32BufferAttribute(colors, 3));
}
