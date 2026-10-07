'use client';

import { type ReactNode, useLayoutEffect, useRef } from 'react';
import { Vector3 } from 'three';

import { anchors } from '@/features/campus/anchors';

/**
 * A DOM element that the scene's projector keeps over a 3D point.
 *
 * Conventions the projector (`OverlayProjector`) reads: `layer` is the
 * stacking order (360° spots 1–2, block labels and businesses 2, route pins
 * 3–4) and ranks labels when they collide; ids starting `pin-` stay, dimmed,
 * behind buildings instead of hiding. Inside, `data-marker` marks the glyph
 * that labels keep clear of, `data-label` text that gives way when it would
 * overlap, and `data-yield` a marker that gives way to a nearer one.
 */
export function MapAnchor({
  id,
  position,
  layer = 0,
  children,
}: {
  id: string;
  position: [number, number, number];
  /** Stacking order among anchors: pins over labels over plain spots. */
  layer?: number;
  children: ReactNode;
}) {
  const element = useRef<HTMLDivElement>(null);
  const [x, y, z] = position;
  useLayoutEffect(() => {
    if (!element.current) return;
    anchors.set(id, {
      element: element.current,
      position: new Vector3(x, y, z),
    });
    return () => {
      anchors.delete(id);
    };
  }, [id, x, y, z]);
  return (
    <div
      ref={element}
      // The projector fades occluded anchors through opacity; ease it.
      className="absolute top-0 left-0 transition-opacity duration-200 ease-out-soft will-change-transform"
      // Off-screen until the projector places it on the next frame.
      style={{ transform: 'translate3d(-200px, -200px, 0)', zIndex: layer }}
    >
      {children}
    </div>
  );
}
