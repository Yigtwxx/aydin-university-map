/**
 * Camera framing of the campus overview: which points belong in the frame and
 * where the camera stands to fit them. Pure (no three.js), so it is tested
 * without a canvas.
 */

/** ENU metres: [east, north]. */
export type EnuPoint = readonly [number, number];

/**
 * Two points closer than this belong to the same place. Wider than the gaps
 * inside the campus (the aviation centre sits ~60 m from its neighbours), much
 * narrower than the distance to a site across the motorway (~380 m).
 */
export const CLUSTER_GAP_M = 150;

/** Camera offset of the overview (from the south-east), per unit distance. */
export const OVERVIEW: readonly [number, number, number] = [0.32, 0.92, 0.62];
/** Share of the free view the framed points may fill. */
export const FILL = 0.86;

/**
 * The points of the largest cluster: points chain into one cluster while each
 * is within `gap` of another (single linkage), so a campus spread over a few
 * hundred metres stays whole while a far-off site (a dormitory across the
 * motorway) drops out. Ties keep the cluster seen first.
 */
export function mainCluster(
  points: readonly EnuPoint[],
  gap = CLUSTER_GAP_M,
): EnuPoint[] {
  if (points.length === 0) return [];
  const parent = points.map((_, i) => i);
  const up = (i: number): number => parent[i] ?? i;
  const root = (i: number): number => {
    let r = i;
    while (up(r) !== r) r = up(r);
    // Path compression keeps later lookups flat.
    while (up(i) !== r) {
      const next = up(i);
      parent[i] = r;
      i = next;
    }
    return r;
  };
  // Bucket by a `gap`-sized grid: neighbours within `gap` sit in the 3x3 cells.
  const cells = new Map<string, number[]>();
  const cellOf = (p: EnuPoint) =>
    [Math.floor(p[0] / gap), Math.floor(p[1] / gap)] as const;
  points.forEach((p, i) => {
    const [cx, cy] = cellOf(p);
    const key = `${cx},${cy}`;
    const bucket = cells.get(key);
    if (bucket) bucket.push(i);
    else cells.set(key, [i]);
  });
  const gap2 = gap * gap;
  points.forEach((p, i) => {
    const [cx, cy] = cellOf(p);
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const j of cells.get(`${cx + dx},${cy + dy}`) ?? []) {
          const q = points[j];
          if (j <= i || !q) continue;
          const d2 = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2;
          if (d2 <= gap2) parent[root(i)] = root(j);
        }
      }
    }
  });
  const sizes = new Map<number, number>();
  let best = root(0);
  for (let i = 0; i < points.length; i++) {
    const r = root(i);
    const size = (sizes.get(r) ?? 0) + 1;
    sizes.set(r, size);
    if (size > (sizes.get(best) ?? 0)) best = r;
  }
  return points.filter((_, i) => root(i) === best);
}

export interface OverviewFrame {
  /** ENU point the camera looks at. */
  centre: EnuPoint;
  /** Camera distance, in units of OVERVIEW (setLookAt's offset). */
  distance: number;
}

/**
 * The free part of the view (right of the panel, above the sheet) as the
 * tangents of its half-angles, seen from the camera.
 */
export interface FreeView {
  tanH: number;
  tanV: number;
}

/**
 * The free part of a `width` x `height` canvas once `left` and `bottom` px are
 * covered, for a camera of vertical field of view `fovDeg`. The projection is
 * offset to centre on it (CampusScene's ViewOffset), so it is symmetric.
 */
export function freeView(
  width: number,
  height: number,
  left: number,
  bottom: number,
  fovDeg: number,
): FreeView {
  const tan = Math.tan((fovDeg * Math.PI) / 360);
  const h = Math.max(1, height);
  return {
    tanH: (tan * Math.max(1, width - left)) / h,
    tanV: (tan * Math.max(1, height - bottom)) / h,
  };
}

/**
 * Three-quarter overview of `points` (on the ground): the point to look at and
 * the camera distance that fits them, in perspective, centred in the free view
 * and filling FILL of it; never closer than `minDistance`.
 */
export function overviewFrame(
  points: readonly EnuPoint[],
  view: FreeView,
  minDistance: number,
): OverviewFrame {
  if (points.length === 0) return { centre: [0, 0], distance: minDistance };
  const [ox, oy, oz] = OVERVIEW;
  const length = Math.hypot(ox, oy, oz);
  const flat = Math.hypot(ox, oz);
  // ENU (east, north, up) axes of the camera. OVERVIEW is in three.js world
  // axes, where z points south.
  const back = [ox / length, -oz / length, oy / length] as const;
  const fwd = [-back[0], -back[1], -back[2]] as const;
  // Forward on the ground, and right of it.
  const ground = [-ox / flat, oz / flat] as const;
  const right = [ground[1], -ground[0], 0] as const;
  const up = [
    right[1] * fwd[2] - right[2] * fwd[1],
    right[2] * fwd[0] - right[0] * fwd[2],
    right[0] * fwd[1] - right[1] * fwd[0],
  ] as const;
  const pitch = Math.atan2(oy, flat);
  const tanH = Math.max(1e-3, view.tanH) * FILL;
  const tanV = Math.max(1e-3, view.tanV) * FILL;

  // Start from the points' middle and a rough fit, then refine: recentre on
  // the middle of their projection and scale the distance to fit.
  let minE = Infinity;
  let maxE = -Infinity;
  let minN = Infinity;
  let maxN = -Infinity;
  for (const [e, n] of points) {
    minE = Math.min(minE, e);
    maxE = Math.max(maxE, e);
    minN = Math.min(minN, n);
    maxN = Math.max(maxN, n);
  }
  let te = (minE + maxE) / 2;
  let tn = (minN + maxN) / 2;
  let d = Math.max(1, Math.hypot(maxE - minE, maxN - minN)) / (2 * tanV);
  for (let step = 0; step < 60; step++) {
    const ce = te + d * back[0];
    const cn = tn + d * back[1];
    const cu = d * back[2];
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const [e, n] of points) {
      const ve = e - ce;
      const vn = n - cn;
      const depth = ve * fwd[0] + vn * fwd[1] - cu * fwd[2];
      const x = (ve * right[0] + vn * right[1]) / depth;
      const y = (ve * up[0] + vn * up[1] - cu * up[2]) / depth;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
    const midX = (minX + maxX) / 2;
    const midY = (minY + maxY) / 2;
    // A screen offset at the target's depth, back on the ground.
    const across = midX * d;
    const along = (midY * d) / Math.sin(pitch);
    te += right[0] * across + ground[0] * along;
    tn += right[1] * across + ground[1] * along;
    const scale = Math.max((maxX - minX) / 2 / tanH, (maxY - minY) / 2 / tanV);
    // A single spot has no extent to fit: keep the floor distance.
    if (!(scale > 1e-9)) break;
    d *= scale;
    if (
      Math.abs(scale - 1) < 1e-6 &&
      Math.abs(midX) < 1e-7 &&
      Math.abs(midY) < 1e-7
    )
      break;
  }
  return {
    centre: [te, tn],
    distance: Math.max(minDistance, d / length),
  };
}
