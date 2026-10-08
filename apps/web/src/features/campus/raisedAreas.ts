import {
  type BufferGeometry,
  Color,
  ExtrudeGeometry,
  Float32BufferAttribute,
  Shape,
  Vector2,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { openRing } from './geometry';

type XY = [number, number];

/** How a traced area stands up: its top and side colours and its height. */
export interface RaisedStyle {
  top: string;
  side: string;
  depth: number;
}

/**
 * Traced areas (lawns, flower beds, pools) as one vertex-coloured mesh: each
 * outline extruded up `depth` from the ground under its centroid, its caps in
 * the top colour and its sides in the side colour. One merged geometry, so
 * every area shares a single material however many there are.
 */
export function raisedAreaGeometry(
  outlines: readonly (readonly XY[])[],
  style: RaisedStyle,
  groundAt: (east: number, north: number) => number,
): BufferGeometry | undefined {
  const top = new Color(style.top);
  const side = new Color(style.side);
  const parts: BufferGeometry[] = [];
  for (const outline of outlines) {
    const ring = openRing([...outline]);
    if (ring.length < 3) continue;
    const g = new ExtrudeGeometry(
      new Shape(ring.map(([e, n]) => new Vector2(e, n))),
      { depth: style.depth, bevelEnabled: false },
    );
    // Shape in (east, north), extruded up: to world (east, up, -north).
    g.rotateX(-Math.PI / 2);
    let ce = 0;
    let cn = 0;
    for (const [e, n] of ring) {
      ce += e;
      cn += n;
    }
    g.translate(0, groundAt(ce / ring.length, cn / ring.length), 0);
    // ExtrudeGeometry's groups: material 0 the caps, 1 the sides.
    const count = g.getAttribute('position').count;
    const colors = new Float32Array(count * 3);
    for (const group of g.groups) {
      const c = group.materialIndex === 0 ? top : side;
      const end = Math.min(count, group.start + group.count);
      for (let v = group.start; v < end; v++) {
        colors[v * 3] = c.r;
        colors[v * 3 + 1] = c.g;
        colors[v * 3 + 2] = c.b;
      }
    }
    g.setAttribute('color', new Float32BufferAttribute(colors, 3));
    g.clearGroups();
    parts.push(g);
  }
  if (parts.length === 0) return undefined;
  const merged = mergeGeometries(parts, false);
  parts.forEach((g) => g.dispose());
  return merged ?? undefined;
}
