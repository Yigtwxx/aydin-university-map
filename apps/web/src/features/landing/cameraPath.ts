/**
 * The landing dive as camera keyframes in local ENU metres (east, north, up)
 * around the campus origin, scrubbed by scroll progress 0..1.
 *
 * Every channel (east, north, log altitude, target, fov) runs through one
 * monotone cubic spline over all keyframes, so the camera never stops at a
 * keyframe: speed changes smoothly along the whole dive, and nothing
 * overshoots (a monotone curve cannot dip below the ground or swing back).
 * Altitude is interpolated in log space, so 30 km -> 1 km feels like a
 * steady descent instead of rushing the last kilometre.
 *
 * The final pose is exactly the map's opening camera (CampusScene
 * INTRO_POSITION, fov 34, looking at the origin): the dive ends in the map.
 */

export interface Keyframe {
  /** Scroll progress at which this pose is reached. */
  at: number;
  eye: [number, number, number];
  target: [number, number, number];
  fov: number;
}

export const KEYFRAMES: Keyframe[] = [
  // High over the city: both straits, the Golden Horn and the Marmara.
  { at: 0, eye: [15500, -9000, 30000], target: [16500, 8000, 0], fov: 46 },
  // Turning west along the Marmara shore, the old airport ahead.
  { at: 0.32, eye: [9500, -6500, 9500], target: [2000, 1500, 0], fov: 44 },
  // Above the cloud deck over Florya; the next stretch dives through it.
  { at: 0.62, eye: [3400, -4800, 4600], target: [200, 0, 0], fov: 40 },
  // The campus, as the map opens it.
  { at: 1, eye: [420, -1500, 1150], target: [0, 0, 0], fov: 34 },
];

export interface Pose {
  eye: [number, number, number];
  target: [number, number, number];
  fov: number;
}

/**
 * Monotone cubic (Fritsch-Carlson) interpolation of ``ys`` over ``xs`` at
 * ``x``: C1-continuous, and never overshoots the keyframe values.
 */
export function monotoneCubic(xs: number[], ys: number[], x: number): number {
  const n = xs.length;
  if (x <= xs[0]!) return ys[0]!;
  if (x >= xs[n - 1]!) return ys[n - 1]!;
  const delta: number[] = [];
  for (let i = 0; i < n - 1; i++)
    delta.push((ys[i + 1]! - ys[i]!) / (xs[i + 1]! - xs[i]!));
  const m: number[] = [delta[0]!];
  for (let i = 1; i < n - 1; i++)
    m.push(
      delta[i - 1]! * delta[i]! <= 0 ? 0 : (delta[i - 1]! + delta[i]!) / 2,
    );
  m.push(delta[n - 2]!);
  for (let i = 0; i < n - 1; i++) {
    if (delta[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i]! / delta[i]!;
    const b = m[i + 1]! / delta[i]!;
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * delta[i]!;
      m[i + 1] = t * b * delta[i]!;
    }
  }
  let k = 0;
  while (k < n - 2 && x > xs[k + 1]!) k++;
  const h = xs[k + 1]! - xs[k]!;
  const t = (x - xs[k]!) / h;
  const t2 = t * t;
  const t3 = t2 * t;
  return (
    (2 * t3 - 3 * t2 + 1) * ys[k]! +
    (t3 - 2 * t2 + t) * h * m[k]! +
    (-2 * t3 + 3 * t2) * ys[k + 1]! +
    (t3 - t2) * h * m[k + 1]!
  );
}

/** Gentle start and arrival over the whole dive (not per keyframe). */
function glide(p: number): number {
  // Ease in over the first 6 % and out over the last 12 % of the scroll.
  const inEnd = 0.06;
  const outStart = 0.88;
  if (p < inEnd)
    return (p * p) / (2 * inEnd) / (1 - inEnd / 2 - (1 - outStart) / 2);
  if (p > outStart) {
    const q = 1 - p;
    const tail = 1 - outStart;
    return 1 - (q * q) / (2 * tail) / (1 - inEnd / 2 - tail / 2);
  }
  return (p - inEnd / 2) / (1 - inEnd / 2 - (1 - outStart) / 2);
}

/** Camera pose at scroll progress ``p`` (clamped to 0..1). */
export function poseAt(p: number, frames: Keyframe[] = KEYFRAMES): Pose {
  const x = glide(Math.min(1, Math.max(0, p)));
  const at = frames.map((f) => f.at);
  const channel = (pick: (f: Keyframe) => number) =>
    monotoneCubic(at, frames.map(pick), x);
  return {
    eye: [
      channel((f) => f.eye[0]),
      channel((f) => f.eye[1]),
      Math.exp(channel((f) => Math.log(f.eye[2]))),
    ],
    target: [
      channel((f) => f.target[0]),
      channel((f) => f.target[1]),
      channel((f) => f.target[2]),
    ],
    fov: channel((f) => f.fov),
  };
}

/** Caption shown at progress ``p`` (index into the landing's captions). */
export function stageAt(p: number): number {
  if (p < 0.24) return 0;
  if (p < 0.52) return 1;
  if (p < 0.82) return 2;
  return 3;
}
