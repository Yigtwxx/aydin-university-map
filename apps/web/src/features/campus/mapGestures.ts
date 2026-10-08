import { Box3, DoubleSide, type Ray, Vector3 } from 'three';
import type { MeshBVH } from 'three-mesh-bvh';

/**
 * Mouse gestures on the campus map, as plain geometry: what the pointer
 * grabs, how a wheel turn scales the view, and where the view may go.
 * `MapPointer` wires them to the camera controls.
 */

/** Farthest a grabbed point may lie: past it the ray grazes the horizon. */
export const GRAB_MAX_M = 4000;
/** Grabbed points sit between the ground and the tallest roof. */
const GRAB_MIN_Y = -15;
const GRAB_MAX_Y = 120;

/** Camera position and the ground point it looks at. */
export interface Pose {
  position: Vector3;
  target: Vector3;
}

/** Where a ray crosses the level `y`, ahead of its origin and within reach. */
export function rayAtHeight(
  ray: Ray,
  y: number,
  out: Vector3,
): Vector3 | undefined {
  const dy = ray.direction.y;
  if (Math.abs(dy) < 1e-6) return undefined;
  const t = (y - ray.origin.y) / dy;
  if (t <= 0 || t > GRAB_MAX_M) return undefined;
  return ray.at(t, out);
}

/**
 * What the pointer is over: the first roof or wall it meets, else the
 * ground. Panning holds this point under the cursor, as Google Earth does,
 * so a roof grabbed moves with the hand instead of sliding under it.
 */
export function pickPoint(
  ray: Ray,
  occluders: Iterable<MeshBVH>,
  out: Vector3,
): Vector3 | undefined {
  let best = Infinity;
  for (const bvh of occluders) {
    const hit = bvh.raycastFirst(ray, DoubleSide, 0, GRAB_MAX_M);
    if (hit && hit.distance < best) {
      best = hit.distance;
      out.copy(hit.point);
    }
  }
  if (best < Infinity && out.y >= GRAB_MIN_Y && out.y <= GRAB_MAX_Y) return out;
  return rayAtHeight(ray, 0, out);
}

/**
 * Wheel event -> zoom factor on the camera distance (below 1 zooms in).
 * Pixel, line and page deltas share a scale; a trackpad pinch (the browser
 * sends it as a wheel with ctrlKey) reports small deltas, so it is geared up.
 * One turn is capped so a fast flick of a free-spinning wheel cannot jump.
 */
export function wheelScale(
  deltaY: number,
  deltaMode: number,
  pinch: boolean,
): number {
  const px =
    deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  const capped = Math.max(-WHEEL_CAP_PX, Math.min(WHEEL_CAP_PX, px));
  return Math.exp(capped * (pinch ? PINCH_GAIN : WHEEL_GAIN));
}
/** About x1.25 per notch of a 100 px mouse wheel. */
const WHEEL_GAIN = 0.0022;
const PINCH_GAIN = 0.012;
const WHEEL_CAP_PX = 160;

/**
 * Zooms about `anchor`: the camera's offset from it scales by `scale`, so the
 * point under the cursor stays under the cursor. The target then slides along
 * the view back onto the ground (a roof anchor would lift it), which keeps
 * the view and only changes how far the orbit pivot lies.
 */
export function zoomAbout(pose: Pose, anchor: Vector3, scale: number): Pose {
  const position = pose.position
    .clone()
    .sub(anchor)
    .multiplyScalar(scale)
    .add(anchor);
  const target = pose.target
    .clone()
    .sub(anchor)
    .multiplyScalar(scale)
    .add(anchor);
  const view = target.clone().sub(position);
  if (Math.abs(view.y) > 1e-6) {
    const t = -position.y / view.y;
    if (t > 0) target.copy(position).addScaledVector(view, t);
  }
  return { position, target };
}

/** Scale that keeps the camera distance within [min, max] after zooming. */
export function clampScale(
  distance: number,
  scale: number,
  min: number,
  max: number,
): number {
  if (distance <= 0) return 1;
  const next = Math.min(max, Math.max(min, distance * scale));
  return next / distance;
}

/** Horizontal shift that brings `target` back inside `bounds`. */
export function boundsShift(
  target: Vector3,
  bounds: Box3,
  out: Vector3,
): Vector3 {
  out.set(
    clamp(target.x, bounds.min.x, bounds.max.x) - target.x,
    0,
    clamp(target.z, bounds.min.z, bounds.max.z) - target.z,
  );
  return out;
}

const clamp = (v: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, v));

/**
 * Throw speed (m/s, horizontal) from the last moments of a drag: the target's
 * positions with their timestamps (ms). A drag that paused before release
 * does not glide.
 */
export function releaseVelocity(
  samples: readonly { t: number; x: number; z: number }[],
  releasedAt: number,
): Vector3 {
  const v = new Vector3();
  const last = samples.at(-1);
  if (!last || releasedAt - last.t > THROW_PAUSE_MS) return v;
  const first = samples.find((s) => last.t - s.t <= THROW_WINDOW_MS) ?? last;
  const dt = (last.t - first.t) / 1000;
  if (dt <= 0.008) return v;
  v.set((last.x - first.x) / dt, 0, (last.z - first.z) / dt);
  return v;
}
const THROW_WINDOW_MS = 90;
const THROW_PAUSE_MS = 60;

/** Room to pan past the campus's outermost spots and blocks (m). */
export const PAN_MARGIN_M = 700;

/**
 * Where the view's target may go: the box around the given ENU points (the
 * walkable spots and campus blocks, far sites included) plus a margin, in
 * world coordinates (x east, z south). Height is free.
 */
export function panBounds(
  points: readonly (readonly [number, number])[],
  margin = PAN_MARGIN_M,
): Box3 {
  const box = new Box3(
    new Vector3(Infinity, -Infinity, Infinity),
    new Vector3(-Infinity, Infinity, -Infinity),
  );
  for (const [e, n] of points) {
    box.min.x = Math.min(box.min.x, e - margin);
    box.max.x = Math.max(box.max.x, e + margin);
    box.min.z = Math.min(box.min.z, -n - margin);
    box.max.z = Math.max(box.max.z, -n + margin);
  }
  if (box.min.x > box.max.x) {
    box.min.x = box.min.z = -Infinity;
    box.max.x = box.max.z = Infinity;
  }
  return box;
}
