import { type Pose, poseAt } from './cameraPath';

/**
 * Scroll-to-scene bridge, outside React: the page writes the scroll target,
 * the scene eases ``progress`` towards it every frame and publishes what the
 * DOM overlays need (altitude for the cloud whiteout, the current pose).
 */
export const landingState: {
  target: number;
  progress: number;
  altitude: number;
  pose: Pose;
  /** The campus on screen (CSS px), for the pin over the final view. */
  campus: { x: number; y: number; visible: boolean };
} = {
  target: 0,
  progress: 0,
  altitude: poseAt(0).eye[2],
  pose: poseAt(0),
  campus: { x: 0, y: 0, visible: false },
};
