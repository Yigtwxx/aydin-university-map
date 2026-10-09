import { Matrix4, Vector3 } from 'three';

/** Shadow-map texels along one side of the sun's frustum. */
export const SHADOW_MAP_PX = 2048;
/** Half-width of the sun's frustum: close up, and over the whole campus. */
export const SHADOW_HALF_MIN_M = 110;
export const SHADOW_HALF_MAX_M = 420;
/** Share of the camera distance the frustum's half-width covers. */
const HALF_PER_DISTANCE = 0.55;
/** Frustum sizes come in steps this far apart, so zooming rarely refits it. */
const HALF_STEP = 1.25;

/**
 * Half-width of the sun's shadow frustum for a camera this far from its
 * target: tight close up (sharp shadows under benches and trees), the whole
 * campus from afar. Quantised into steps so the shadows do not crawl while
 * zooming.
 */
export function shadowHalfWidth(cameraDistance: number): number {
  const want = Math.min(
    SHADOW_HALF_MAX_M,
    Math.max(SHADOW_HALF_MIN_M, cameraDistance * HALF_PER_DISTANCE),
  );
  const steps = Math.ceil(
    Math.log(want / SHADOW_HALF_MIN_M) / Math.log(HALF_STEP) - 1e-9,
  );
  return Math.min(SHADOW_HALF_MAX_M, SHADOW_HALF_MIN_M * HALF_STEP ** steps);
}

const UP = new Vector3(0, 1, 0);
const ORIGIN = new Vector3();

/**
 * Moves the shadow frustum's centre to the nearest whole shadow texel as the
 * sun sees it, so the shadow edges stay put while the map pans instead of
 * shimmering. `sun` points from the ground towards the light (world axes).
 */
export function snapToTexel(
  centre: Vector3,
  sun: Vector3,
  texel: number,
  out = new Vector3(),
): Vector3 {
  const basis = new Matrix4().lookAt(sun, ORIGIN, UP);
  const inverse = basis.clone().transpose();
  out.copy(centre).applyMatrix4(inverse);
  out.x = Math.round(out.x / texel) * texel;
  out.y = Math.round(out.y / texel) * texel;
  return out.applyMatrix4(basis);
}
