import type { CameraControls } from '@react-three/drei';
import { create } from 'zustand';

export type ZoomTier = 'near' | 'mid' | 'far';

/** Bridge between the 3D scene's camera and the DOM map controls. */
interface CameraState {
  controls?: CameraControls;
  /** Compass bearing the camera looks towards, degrees clockwise from north. */
  headingDeg: number;
  /** True when looking straight down (2D map view). */
  topDown: boolean;
  /** Bumped to ask the scene to frame the route (or the campus) again. */
  fitRequest: number;
  /** Camera distance bucket; DOM overlays show more detail up close. */
  tier: ZoomTier;
  /** Google's photorealistic campus instead of the drawn massing. */
  photoreal: boolean;
  setPhotoreal: (photoreal: boolean) => void;
  setControls: (controls?: CameraControls) => void;
  setHeading: (headingDeg: number) => void;
  setTopDown: (topDown: boolean) => void;
  requestFit: () => void;
  setTier: (tier: ZoomTier) => void;
}

export const useCameraStore = create<CameraState>((set) => ({
  controls: undefined,
  headingDeg: 0,
  topDown: false,
  fitRequest: 0,
  tier: 'mid',
  photoreal: false,
  setPhotoreal: (photoreal) => set({ photoreal }),
  setControls: (controls) => set({ controls }),
  setHeading: (headingDeg) => set({ headingDeg }),
  setTopDown: (topDown) => set({ topDown }),
  requestFit: () => set((s) => ({ fitRequest: s.fitRequest + 1 })),
  setTier: (tier) => set({ tier }),
}));

/** Polar angles (from straight up) of the two camera modes. */
export const POLAR_3D = 0.95;
export const POLAR_TOP_DOWN = 0.001;

/**
 * Camera-controls azimuth (radians, camera position around the target, 0 when
 * the camera sits south of the target looking north) -> compass heading.
 */
export function headingFromAzimuth(azimuth: number): number {
  const deg = (-azimuth * 180) / Math.PI;
  return ((deg % 360) + 360) % 360;
}
