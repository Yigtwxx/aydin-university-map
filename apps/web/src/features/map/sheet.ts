/**
 * Mobile bottom sheet geometry: three snap points and how a drag settles on
 * one of them. Pure functions, so the gesture math is unit tested.
 */

export const SNAPS = ['peek', 'half', 'full'] as const;
export type SheetSnap = (typeof SNAPS)[number];
export type SnapHeights = Record<SheetSnap, number>;

/** Peek: the handle, the tabs and the search field or the route summary. */
export const PEEK_PX = 140;
/** The sheet floats this far above the bottom edge (Tailwind `bottom-2`). */
export const SHEET_MARGIN_PX = 8;
/** At full height the sheet still leaves the status pill row visible. */
const TOP_CLEARANCE_PX = 60;
/** How far ahead a release is projected along its velocity (seconds). */
const PROJECTION_S = 0.2;
/** Past the first and last snap the sheet follows the finger at this rate. */
const RUBBER_BAND = 0.18;

/** Card heights (px) for a viewport height, always peek < half < full. */
export function snapHeights(viewportHeight: number): SnapHeights {
  const full = Math.max(
    PEEK_PX + 2,
    Math.min(
      Math.round(viewportHeight * 0.92),
      viewportHeight - TOP_CLEARANCE_PX,
    ),
  );
  const half = Math.min(
    full - 1,
    Math.max(PEEK_PX + 1, Math.round(viewportHeight * 0.5)),
  );
  return { peek: PEEK_PX, half, full };
}

/** Height the sheet covers from the bottom edge, margin included. */
export function coveredHeight(cardHeight: number): number {
  return cardHeight + SHEET_MARGIN_PX;
}

/**
 * Snap a released drag: project the height along the release velocity (so a
 * flick carries on to the next snap) and take the nearest snap point.
 *
 * @param height current card height (px)
 * @param velocity growth speed of the height (px/s, positive = upwards)
 */
export function pickSnap(
  height: number,
  velocity: number,
  heights: SnapHeights,
): SheetSnap {
  const projected = height + velocity * PROJECTION_S;
  let best: SheetSnap = 'peek';
  for (const snap of SNAPS)
    if (
      Math.abs(heights[snap] - projected) < Math.abs(heights[best] - projected)
    )
      best = snap;
  return best;
}

/** Follows the finger between the snaps, resists past them. */
export function rubberBand(raw: number, min: number, max: number): number {
  if (raw > max) return max + (raw - max) * RUBBER_BAND;
  if (raw < min) return min - (min - raw) * RUBBER_BAND;
  return raw;
}

/** The handle button: peek → half → full → peek. */
export function cycleSnap(snap: SheetSnap): SheetSnap {
  return SNAPS[(SNAPS.indexOf(snap) + 1) % SNAPS.length] ?? 'peek';
}

/** One snap up (Arrow Up), staying at full. */
export function raiseSnap(snap: SheetSnap): SheetSnap {
  return SNAPS[Math.min(SNAPS.indexOf(snap) + 1, SNAPS.length - 1)] ?? snap;
}

/** One snap down (Escape, Arrow Down), staying at peek. */
export function lowerSnap(snap: SheetSnap): SheetSnap {
  return SNAPS[Math.max(SNAPS.indexOf(snap) - 1, 0)] ?? snap;
}
