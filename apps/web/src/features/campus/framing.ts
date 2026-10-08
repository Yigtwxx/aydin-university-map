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

const OVERVIEW_PITCH_DEG =
  (Math.atan2(OVERVIEW[1], Math.hypot(OVERVIEW[0], OVERVIEW[2])) * 180) /
  Math.PI;
/**
 * Looks at a route, tried in turn until one sees enough of it past the
 * buildings: from the overview's own side, ever steeper (80 degrees at most:
 * steeper reads as the 2D view), then, for a route hugging the far side of
 * a tall block, from the other sides. [bearing turn, pitch] in degrees.
 */
export const ROUTE_LOOKS: readonly (readonly [number, number])[] = [
  [0, OVERVIEW_PITCH_DEG],
  [0, 64],
  [0, 72],
  [0, 80],
  [180, OVERVIEW_PITCH_DEG],
  [90, OVERVIEW_PITCH_DEG],
  [-90, OVERVIEW_PITCH_DEG],
  [180, 72],
  [90, 72],
  [-90, 72],
];
/** A route view may hide this share of the route behind buildings. */
export const MAX_HIDDEN = 0.1;

/**
 * Camera offset per unit distance: OVERVIEW's bearing turned `turnDeg`
 * (clockwise seen from above) at `pitchDeg` above the horizon.
 */
export function overviewDirection(
  pitchDeg: number,
  turnDeg = 0,
): readonly [number, number, number] {
  const flat = Math.hypot(OVERVIEW[0], OVERVIEW[2]);
  const t = (turnDeg * Math.PI) / 180;
  // Clockwise from above: east to south (three.js +x to +z).
  const x = OVERVIEW[0] * Math.cos(t) - OVERVIEW[2] * Math.sin(t);
  const z = OVERVIEW[0] * Math.sin(t) + OVERVIEW[2] * Math.cos(t);
  return [x, flat * Math.tan((pitchDeg * Math.PI) / 180), z];
}

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
  direction: readonly [number, number, number] = OVERVIEW,
): OverviewFrame {
  if (points.length === 0) return { centre: [0, 0], distance: minDistance };
  const [ox, oy, oz] = direction;
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

/** A building's mass for line-of-sight tests: its ring, height and underside. */
export interface Mass {
  ring: readonly EnuPoint[];
  height: number;
  /** A raised slab (a canopy) lets the eye through below it. */
  base?: number;
}

function inRing(e: number, n: number, ring: readonly EnuPoint[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [ei, ni] = ring[i]!;
    const [ej, nj] = ring[j]!;
    if (ni > n !== nj > n && e < ((ej - ei) * (n - ni)) / (nj - ni) + ei)
      inside = !inside;
  }
  return inside;
}

/** The route ribbon's height above the ground (RouteRibbon's lift), metres. */
const EYE_M = 0.3;
/** Parapets, cornices and roof boxes stand this much above `height`. */
const ROOF_MARGIN_M = 1.5;

/**
 * Share of `route` (sampled every ~2 m) that buildings hide from a camera
 * framing it as `frame` from `direction` (setLookAt's offset, three.js axes:
 * x east, y up, z south).
 */
export function hiddenShare(
  route: readonly EnuPoint[],
  frame: OverviewFrame,
  direction: readonly [number, number, number],
  allMasses: readonly Mass[],
): number {
  let masses = allMasses;
  const samples: EnuPoint[] = [];
  for (let i = 0; i < route.length; i++) {
    const a = route[i]!;
    const b = route[i + 1];
    samples.push(a);
    if (!b) break;
    const steps = Math.floor(Math.hypot(b[0] - a[0], b[1] - a[1]) / 2);
    for (let k = 1; k < steps; k++)
      samples.push([
        a[0] + ((b[0] - a[0]) * k) / steps,
        a[1] + ((b[1] - a[1]) * k) / steps,
      ]);
  }
  if (samples.length === 0) return 0;
  const camE = frame.centre[0] + frame.distance * direction[0];
  const camN = frame.centre[1] - frame.distance * direction[2];
  const camU = frame.distance * direction[1];
  // Only masses near the route can stand between it and the camera: within
  // the run of a ray up to the tallest roof (at the shallowest pitch tried).
  let minE = Infinity;
  let maxE = -Infinity;
  let minN = Infinity;
  let maxN = -Infinity;
  for (const [e, n] of samples) {
    minE = Math.min(minE, e);
    maxE = Math.max(maxE, e);
    minN = Math.min(minN, n);
    maxN = Math.max(maxN, n);
  }
  const allTallest = allMasses.reduce((m, b) => Math.max(m, b.height), 0);
  const slope = direction[1] / Math.hypot(direction[0], direction[2]);
  const margin = (allTallest + ROOF_MARGIN_M) / Math.max(slope, 0.1) + 2;
  const near = masses.filter((b) => {
    let bMinE = Infinity;
    let bMaxE = -Infinity;
    let bMinN = Infinity;
    let bMaxN = -Infinity;
    for (const [e, n] of b.ring) {
      bMinE = Math.min(bMinE, e);
      bMaxE = Math.max(bMaxE, e);
      bMinN = Math.min(bMinN, n);
      bMaxN = Math.max(bMaxN, n);
    }
    return (
      bMaxE >= minE - margin &&
      bMinE <= maxE + margin &&
      bMaxN >= minN - margin &&
      bMinN <= maxN + margin
    );
  });
  masses = near;
  const tallest =
    masses.reduce((m, b) => Math.max(m, b.height), 0) + ROOF_MARGIN_M;
  const boxes = masses.map((b) => {
    let minE = Infinity;
    let maxE = -Infinity;
    let minN = Infinity;
    let maxN = -Infinity;
    for (const [e, n] of b.ring) {
      minE = Math.min(minE, e);
      maxE = Math.max(maxE, e);
      minN = Math.min(minN, n);
      maxN = Math.max(maxN, n);
    }
    return { minE, maxE, minN, maxN };
  });
  let hidden = 0;
  for (const [pe, pn] of samples) {
    const flat = Math.hypot(camE - pe, camN - pn);
    // Past the tallest roof the ray is clear; walk it in 1 m steps till then.
    const rise = (camU - EYE_M) / Math.max(flat, 1e-6);
    const reach = Math.min(flat, (tallest - EYE_M) / Math.max(rise, 1e-6));
    let blocked = false;
    for (let t = 0.5; t <= reach && !blocked; t += 1) {
      const e = pe + ((camE - pe) * t) / flat;
      const n = pn + ((camN - pn) * t) / flat;
      const u = EYE_M + rise * t;
      blocked = masses.some((m, i) => {
        const box = boxes[i]!;
        return (
          m.height + ROOF_MARGIN_M > u &&
          (m.base ?? 0) < u &&
          e >= box.minE &&
          e <= box.maxE &&
          n >= box.minN &&
          n <= box.maxN &&
          inRing(e, n, m.ring)
        );
      });
    }
    if (blocked) hidden += 1;
  }
  return hidden / samples.length;
}

/**
 * The view of a route: the first of ROUTE_LOOKS that hides at most
 * MAX_HIDDEN of it behind buildings (else the clearest one), so a route
 * along the far side of a tall block is not drawn only as dashes.
 */
export function routeView(
  points: readonly EnuPoint[],
  route: readonly EnuPoint[],
  view: FreeView,
  minDistance: number,
  masses: readonly Mass[],
): { frame: OverviewFrame; direction: readonly [number, number, number] } {
  let best:
    | {
        frame: OverviewFrame;
        direction: readonly [number, number, number];
        hidden: number;
      }
    | undefined;
  for (const [i, [turn, pitch]] of ROUTE_LOOKS.entries()) {
    const direction = i === 0 ? OVERVIEW : overviewDirection(pitch, turn);
    const frame = overviewFrame(points, view, minDistance, direction);
    const hidden = hiddenShare(route, frame, direction, masses);
    if (hidden <= MAX_HIDDEN) return { frame, direction };
    if (!best || hidden < best.hidden - 1e-9)
      best = { frame, direction, hidden };
  }
  return { frame: best!.frame, direction: best!.direction };
}
