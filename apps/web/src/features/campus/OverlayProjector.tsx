'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useRef } from 'react';
import { Matrix4 } from 'three';

import { type ZoomTier, useCameraStore } from '@/features/map/cameraStore';

import { anchors, isOccluded, projectToScreen } from './anchors';

const NEAR_M = 260;
const FAR_M = 950;
/** Route pins stay findable behind buildings, just dimmed. */
const DIMMED_PREFIX = 'pin-';
const DIMMED_OPACITY = '0.6';
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

function boxOf(element: Element): Placed | undefined {
  const r = element.getBoundingClientRect();
  if (r.width === 0) return undefined;
  return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
}

/**
 * Hide labels that would overlap a more important one: higher layer first
 * (pins, blocks, entrances), then nearer to the camera. A label also gives
 * way to the markers (pins, block chips, dots) of its own layer and above,
 * and to the map's own chrome (`data-map-obstacle`). Only the text hides;
 * the markers stay.
 */
function declutter(visible: { element: HTMLElement; depth: number }[]): void {
  const ranked = visible
    .map((v) => ({ ...v, layer: Number(v.element.style.zIndex || 0) }))
    .sort((a, b) => b.layer - a.layer || a.depth - b.depth);
  const chrome: Placed[] = [];
  for (const element of document.querySelectorAll('[data-map-obstacle]')) {
    const box = boxOf(element);
    if (box) chrome.push(box);
  }
  const markers = ranked.map(({ element, layer }) => ({
    element,
    layer,
    boxes: [...element.querySelectorAll('[data-marker]')]
      .map(boxOf)
      .filter((b): b is Placed => !!b),
  }));
  const placed: Placed[] = [];
  for (const { element, layer } of ranked) {
    for (const label of element.querySelectorAll<HTMLElement>('[data-label]')) {
      const box = boxOf(label);
      if (!box) continue;
      const hidden =
        placed.some((p) => overlaps(p, box)) ||
        chrome.some((p) => overlaps(p, box)) ||
        markers.some(
          (m) =>
            m.element !== element &&
            m.layer >= layer &&
            m.boxes.some((p) => overlaps(p, box)),
        );
      label.style.opacity = hidden ? '0' : '';
      if (!hidden) placed.push(box);
    }
  }
  // Block chips and business pins (`data-yield`) that would sit on each
  // other: the nearer one stays; zooming in brings the others back. A pin
  // that gives way is out of reach too (no click, no tab stop).
  const chips: Placed[] = [];
  for (const { element } of ranked) {
    for (const chip of element.querySelectorAll<HTMLElement>('[data-yield]')) {
      const box = boxOf(chip);
      if (!box) continue;
      const hidden = chips.some((p) => overlaps(p, box));
      chip.style.opacity = hidden ? '0' : '';
      chip.inert = hidden;
      if (!hidden) chips.push(box);
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
    // camera-controls moves the camera earlier this frame but leaves its
    // matrices to the renderer; project with last frame's and the markers
    // trail the scene by a frame whenever the view moves.
    camera.updateMatrixWorld();
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
      const dimmed = id.startsWith(DIMMED_PREFIX);
      // Pins stay (dimmed) behind buildings, so their labels still claim space.
      if (!occluded || dimmed)
        labelled.push({
          element,
          depth: anchor.position.distanceToSquared(camera.position),
        });
      if (occluded === (element.dataset.occluded === 'true')) continue;
      element.dataset.occluded = occluded ? 'true' : 'false';
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
