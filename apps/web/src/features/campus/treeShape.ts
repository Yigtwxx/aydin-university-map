/**
 * Size and proportions of one tree on the map, from its greenery.json record.
 *
 * A record is `[east, north]` or `[east, north, height_m]`, the height being
 * the whole tree from the ground to the crown top. The pipeline always writes
 * the height; older files without it fall back to `DEFAULT_TREE_M`.
 */

export type TreeRecord = [number, number] | [number, number, number];

/** Height for a record without one (older greenery.json), metres. */
export const DEFAULT_TREE_M = 6;
/** Per-tree height variation, as a fraction either way. */
export const HEIGHT_JITTER = 0.15;
/** Crown radius as a fraction of the whole tree's height. */
export const CROWN_RATIO = 0.36;
/** Crown's vertical semi-axis relative to its radius (a little flattened). */
export const CROWN_SQUASH = 0.9;

export interface TreeShape {
  /** Whole tree, ground to crown top, metres. */
  height: number;
  /** Horizontal crown radius, metres. */
  crownRadius: number;
  /** Vertical crown semi-axis, metres. */
  crownHalfHeight: number;
  /** Crown centre above the ground, metres. */
  crownY: number;
  /** Trunk from the ground to the crown centre, metres. */
  trunkHeight: number;
  /** Trunk radius at its foot, metres. */
  trunkRadius: number;
  /** Rotation about the vertical axis, radians. */
  yaw: number;
  /** Lightness offset for the crown colour, about -0.04..0.04. */
  shade: number;
}

/**
 * Stable pseudo-random value in [0, 1) from a tree's position, so the same
 * tree keeps its look whatever its order in the file.
 */
export function positionHash(
  east: number,
  north: number,
  salt: number,
): number {
  const e = Math.round(east * 10);
  const n = Math.round(north * 10);
  const x = Math.sin(e * 12.9898 + n * 78.233 + salt * 37.719) * 43758.5453;
  return x - Math.floor(x);
}

export function treeShape(tree: TreeRecord): TreeShape {
  const [east, north] = tree;
  const base = tree[2] !== undefined && tree[2] > 0 ? tree[2] : DEFAULT_TREE_M;
  const height =
    base *
    (1 - HEIGHT_JITTER + 2 * HEIGHT_JITTER * positionHash(east, north, 1));
  const crownRadius =
    height * CROWN_RATIO * (0.92 + 0.16 * positionHash(east, north, 2));
  const crownHalfHeight = crownRadius * CROWN_SQUASH;
  const crownY = height - crownHalfHeight;
  return {
    height,
    crownRadius,
    crownHalfHeight,
    crownY,
    // The trunk ends inside the crown, at its centre.
    trunkHeight: crownY,
    trunkRadius: Math.min(0.4, Math.max(0.08, 0.035 * height)),
    yaw: positionHash(east, north, 3) * Math.PI,
    shade: (positionHash(east, north, 4) - 0.5) * 0.08,
  };
}
