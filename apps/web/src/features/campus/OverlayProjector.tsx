'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useRef } from 'react';
import { Matrix4 } from 'three';

import { type ZoomTier, useCameraStore } from '@/features/map/cameraStore';

import { anchors, isOccluded, projectToScreen } from './anchors';

const NEAR_M = 260;
const FAR_M = 720;
/** Route pins stay findable behind buildings, just dimmed. */
const DIMMED_PREFIX = 'pin-';
const DIMMED_OPACITY = '0.38';
/** Gap kept between map labels, CSS px. */
const LABEL_GAP = 4;

interface Placed {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

function overlaps(a: Placed, b: Placed): boolean {
  return (
    a.left < b.right + LABEL_GAP &&
    b.left < a.right + LABEL_GAP &&
    a.top < b.bottom + LABEL_GAP &&
    b.top < a.bottom + LABEL_GAP
  );
}

/**
 * Hide labels that would overlap a more important one: higher layer first
 * (pins, blocks, entrances), then nearer to the camera. Only the text hides;
 * the marker itself stays.
 */
function declutter(visible: { element: HTMLElement; depth: number }[]): void {
  const ranked = visible
    .map((v) => ({ ...v, layer: Number(v.element.style.zIndex || 0) }))
    .sort((a, b) => b.layer - a.layer || a.depth - b.depth);
  const placed: Placed[] = [];
  for (const { element } of ranked) {
    for (const label of element.querySelectorAll<HTMLElement>('[data-label]')) {
      const r = label.getBoundingClientRect();
      if (r.width === 0) continue;
      const box = {
        left: r.left,
        top: r.top,
        right: r.right,
        bottom: r.bottom,
      };
      const hidden = placed.some((p) => overlaps(p, box));
      label.style.opacity = hidden ? '0' : '';
      if (!hidden) placed.push(box);
    }
  }
}

/**
 * Moves every registered DOM anchor to its projected screen position, hides
 * the ones a building stands in front of, and publishes the zoom tier, which
 * DOM overlays use to show or hide detail.
 */
export function OverlayProjector() {
  const size = useThree((s) => s.size);
  const controls = useThree((s) => s.controls) as { distance?: number } | null;
  const setTier = useCameraStore((s) => s.setTier);
  const tier = useRef<ZoomTier | undefined>(undefined);
  const lastView = useRef(new Matrix4());
  const lastCount = useRef(-1);

  useFrame(({ camera }) => {
    // Occlusion only changes when the camera or the set of anchors does.
    const moved =
      !lastView.current.equals(camera.matrixWorld) ||
      lastCount.current !== anchors.size;
    if (moved) {
      lastView.current.copy(camera.matrixWorld);
      lastCount.current = anchors.size;
    }
    const labelled: { element: HTMLElement; depth: number }[] = [];
    for (const [id, anchor] of anchors) {
      const screen = projectToScreen(
        anchor.position,
        camera,
        size.width,
        size.height,
      );
      const element = anchor.element;
      const style = element.style;
      if (!screen) {
        style.visibility = 'hidden';
        continue;
      }
      style.visibility = '';
      style.transform = `translate3d(${screen[0].toFixed(1)}px, ${screen[1].toFixed(1)}px, 0)`;
      if (!moved) continue;
      const occluded = isOccluded(anchor.position, camera.position);
      if (!occluded)
        labelled.push({
          element,
          depth: anchor.position.distanceToSquared(camera.position),
        });
      if (occluded === (element.dataset.occluded === 'true')) continue;
      element.dataset.occluded = occluded ? 'true' : 'false';
      const dimmed = id.startsWith(DIMMED_PREFIX);
      style.opacity = occluded ? (dimmed ? DIMMED_OPACITY : '0') : '';
      style.pointerEvents = occluded && !dimmed ? 'none' : '';
    }
    // Reads layout once, after every transform of this frame is written.
    if (moved) declutter(labelled);
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
