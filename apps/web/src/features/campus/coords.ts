/**
 * Local ENU metres (x east, y north, z up) -> three.js world (x east, y up, z south).
 * Keeping this in one place avoids sign slips between map and scene.
 */
export function enuToWorld(
  east: number,
  north: number,
  up = 0,
): [number, number, number] {
  return [east, up, -north];
}

/** Compass bearing (clockwise from north) from a to b in ENU metres. */
export function bearingDeg(a: [number, number], b: [number, number]): number {
  const deg = (Math.atan2(b[0] - a[0], b[1] - a[1]) * 180) / Math.PI;
  return (deg + 360) % 360;
}

/**
 * Viewer yaw (radians, clockwise from the front face) that looks along a
 * compass bearing, given the panorama's front-face heading.
 */
export function yawForBearing(
  bearingDegrees: number,
  headingDegrees: number,
): number {
  const rel = (((bearingDegrees - headingDegrees) % 360) + 360) % 360;
  return (rel * Math.PI) / 180;
}

/** Eight-way compass index (0 = north, clockwise), matching the API's wording. */
export function compassIndex(bearingDegrees: number): number {
  return Math.round((((bearingDegrees % 360) + 360) % 360) / 45) % 8;
}
