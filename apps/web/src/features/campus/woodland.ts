import {
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  IcosahedronGeometry,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { openRing } from './geometry';
import { pointInRing } from './terrain';
import { positionHash, type TreeRecord } from './treeShape';

type XY = [number, number];

/** Spacing of planted woods' trees and the most the map plants in all. */
export const WOOD_SPACING_M = 13;
export const WOOD_MAX_TREES = 2400;
/** Tree heights in the woods, metres. */
const WOOD_HEIGHT_M = [7, 12] as const;

/**
 * Trees for the areas mapped as woods: a jittered grid inside each outline,
 * stable for the same data (seeded by position), capped in total so a large
 * forest cannot flood the GPU.
 */
export function woodTrees(
  outlines: readonly XY[][],
  spacing = WOOD_SPACING_M,
  limit = WOOD_MAX_TREES,
): TreeRecord[] {
  const out: TreeRecord[] = [];
  for (const outline of outlines) {
    const ring = openRing(outline);
    if (ring.length < 3) continue;
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const [x, y] of ring) {
      x0 = Math.min(x0, x);
      y0 = Math.min(y0, y);
      x1 = Math.max(x1, x);
      y1 = Math.max(y1, y);
    }
    // Snap the grid to the world, so neighbouring woods line up.
    const gx0 = Math.floor(x0 / spacing);
    const gy0 = Math.floor(y0 / spacing);
    for (let gy = gy0; gy * spacing <= y1; gy++) {
      for (let gx = gx0; gx * spacing <= x1; gx++) {
        const jx = positionHash(gx, gy, 11) - 0.5;
        const jy = positionHash(gx, gy, 12) - 0.5;
        const e = (gx + 0.5 + jx * 0.8) * spacing;
        const n = (gy + 0.5 + jy * 0.8) * spacing;
        if (!pointInRing(e, n, ring)) continue;
        const h =
          WOOD_HEIGHT_M[0] +
          (WOOD_HEIGHT_M[1] - WOOD_HEIGHT_M[0]) * positionHash(gx, gy, 13);
        out.push([e, n, h]);
        if (out.length >= limit) return out;
      }
    }
  }
  return out;
}

/**
 * Lobes of a broadleaf crown in unit space (radius about 1): a big middle
 * lobe, three round its flanks and one on top, so the crown reads as a
 * clump of foliage rather than a ball.
 */
const LOBES: readonly [number, number, number, number][] = [
  [0, 0.08, 0, 0.78],
  [0.44, -0.16, 0.12, 0.58],
  [-0.36, -0.12, 0.34, 0.56],
  [-0.06, -0.18, -0.46, 0.56],
  [0.1, 0.5, -0.06, 0.5],
];

/**
 * A crown of overlapping lobes with smooth shading, darkened towards its
 * underside (vertex colours) where the foliage shades itself. `detail`
 * subdivides each lobe (0 for the far woods, 1 near the campus).
 */
export function crownGeometry(detail = 1): BufferGeometry {
  const parts = LOBES.map(([x, y, z, r]) => {
    const lobe = new IcosahedronGeometry(r, detail);
    lobe.translate(x, y, z);
    return lobe;
  });
  const merged = mergeGeometries(parts, false);
  for (const part of parts) part.dispose();
  const position = merged.getAttribute('position');
  const colors: number[] = [];
  const shade = new Color();
  for (let i = 0; i < position.count; i++) {
    // 0 at the crown's bottom, 1 at its top.
    const t = Math.min(1, Math.max(0, (position.getY(i) + 0.75) / 1.75));
    const k = 0.62 + 0.46 * t;
    shade.setRGB(k, k, k);
    colors.push(shade.r, shade.g, shade.b);
  }
  merged.setAttribute('color', new Float32BufferAttribute(colors, 3));
  return merged;
}
