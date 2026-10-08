import type { Walkway } from './furniture';
import { pointInRing } from './terrain';

type XY = [number, number];

/** A stretch counts as walked up there when it passes a panorama taken on
 * the walkway this close (smoothing moves a route's spots ~0.35 m). */
const SPOT_M = 0.75;

/**
 * Per route point, the walkway floor height where the route walks up on a
 * raised walkway; undefined on the ground (the terrain decides there).
 *
 * The ground under a slab or a footbridge keeps its own level, so a point
 * inside a walkway's outline is not up there by its position alone: a
 * stretch inside it is when it passes one of the walkway's panoramas. The
 * walking graph reaches a walkway only through them.
 */
export function deckHeights(
  points: readonly XY[],
  walkways: readonly Walkway[],
  spotAt: (id: string) => XY | undefined,
): (number | undefined)[] {
  const heights: (number | undefined)[] = points.map(() => undefined);
  for (const walkway of walkways) {
    const ring = walkway.outline as XY[];
    const spots = walkway.spots
      .map(spotAt)
      .filter((p): p is XY => p !== undefined);
    if (spots.length === 0) continue;
    let start = -1;
    for (let i = 0; i <= points.length; i++) {
      const inside =
        i < points.length && pointInRing(points[i]![0], points[i]![1], ring);
      if (inside && start < 0) start = i;
      if (inside || start < 0) continue;
      const run = points.slice(start, i);
      const up = run.some(([e, n]) =>
        spots.some(([se, sn]) => Math.hypot(e - se, n - sn) <= SPOT_M),
      );
      if (up) for (let k = start; k < i; k++) heights[k] = walkway.z_m;
      start = -1;
    }
  }
  return heights;
}
