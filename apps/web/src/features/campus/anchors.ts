import { type Camera, Vector3 } from 'three';

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
