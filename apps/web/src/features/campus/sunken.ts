import {
  AlwaysStencilFunc,
  NotEqualStencilFunc,
  ReplaceStencilOp,
} from 'three';

import type { TerraceShape } from './terrain';

type XY = [number, number];

/**
 * A terrace sunk below the street datum (a garden a storey down) lies under
 * the street-level ground: the base plane and the flat layers at the datum.
 * Its opening is written to the stencil buffer first, and those street-level
 * surfaces skip the pixels it covers, so the pit shows through.
 */
export function sunkenOpenings(terraces: readonly TerraceShape[]): XY[][] {
  return terraces.filter((t) => t.parent < 0 && t.z < 0).map((t) => t.ring);
}

/** Material props of the invisible opening: stencil 1 where it covers. */
export const OPENING_MASK = {
  colorWrite: false,
  depthWrite: false,
  stencilWrite: true,
  stencilRef: 1,
  stencilFunc: AlwaysStencilFunc,
  stencilZPass: ReplaceStencilOp,
} as const;

/** Material props of a street-level surface: not drawn over an opening. */
export const STREET_LEVEL = {
  stencilWrite: true,
  stencilRef: 1,
  stencilFunc: NotEqualStencilFunc,
} as const;

/** The mask is drawn first, just above the street-level layers. */
export const OPENING_ORDER = -1;
export const OPENING_LIFT_M = 0.08;
