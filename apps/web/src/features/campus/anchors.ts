import { type Camera, DoubleSide, Ray, Vector3 } from 'three';
import type { MeshBVH } from 'three-mesh-bvh';

/**
 * DOM elements pinned to points in the 3D scene. Markers and labels render
 * as ordinary React DOM above the canvas (with translations, tooltips and
 * keyboard focus); the scene's projector moves them every frame without
 * re-rendering React.
 */
export interface Anchor {
  element: HTMLElement;
  position: Vector3;
}

export const anchors = new Map<string, Anchor>();

/**
 * Geometry that hides anchors behind it (the building massing, in world
 * coordinates). DOM overlays have no depth test of their own: without this a
 * spot behind a block would float on its roof.
 */
export const occluders = new Set<MeshBVH>();

const projected = new Vector3();

/** Screen position (CSS px) of a world point, or undefined behind the camera. */
export function projectToScreen(
  position: Vector3,
  camera: Camera,
  width: number,
  height: number,
): [number, number] | undefined {
  projected.copy(position).project(camera);
  if (projected.z > 1) return undefined;
  return [
    (projected.x * 0.5 + 0.5) * width,
    (-projected.y * 0.5 + 0.5) * height,
  ];
}

const ray = new Ray();
const toPoint = new Vector3();

/** Whether a building stands between the camera and ``position``. */
export function isOccluded(position: Vector3, eye: Vector3): boolean {
  toPoint.subVectors(position, eye);
  // Ignore hits within a metre of the point: a spot at a facade still shows.
  const distance = toPoint.length() - 1;
  if (distance <= 0) return false;
  ray.set(eye, toPoint.normalize());
  for (const bvh of occluders) {
    const hit = bvh.raycastFirst(ray, DoubleSide, 0, distance);
    if (hit) return true;
  }
  return false;
}
