'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useRef } from 'react';

import { type ZoomTier, useCameraStore } from '@/features/map/cameraStore';

import { anchors, projectToScreen } from './anchors';

const NEAR_M = 260;
const FAR_M = 720;

/**
 * Moves every registered DOM anchor to its projected screen position and
 * publishes the zoom tier, which DOM overlays use to show or hide detail.
 */
export function OverlayProjector() {
  const size = useThree((s) => s.size);
  const controls = useThree((s) => s.controls) as { distance?: number } | null;
  const setTier = useCameraStore((s) => s.setTier);
  const tier = useRef<ZoomTier | undefined>(undefined);

  useFrame(({ camera }) => {
    for (const anchor of anchors.values()) {
      const screen = projectToScreen(
        anchor.position,
        camera,
        size.width,
        size.height,
      );
      const style = anchor.element.style;
      if (!screen) {
        style.visibility = 'hidden';
        continue;
      }
      style.visibility = '';
      style.transform = `translate3d(${screen[0].toFixed(1)}px, ${screen[1].toFixed(1)}px, 0)`;
    }
    const distance = controls?.distance ?? camera.position.length();
    const next: ZoomTier =
      distance < NEAR_M ? 'near' : distance < FAR_M ? 'mid' : 'far';
    if (next !== tier.current) {
      tier.current = next;
      setTier(next);
    }
  });
  return null;
}
