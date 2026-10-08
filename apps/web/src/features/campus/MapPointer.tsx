'use client';

import { type CameraControls, CameraControlsImpl } from '@react-three/drei';
import { type RootState, useFrame, useThree } from '@react-three/fiber';
import { type RefObject, useEffect, useRef } from 'react';
import {
  type Box3,
  type Camera,
  PerspectiveCamera,
  Raycaster,
  Vector2,
  Vector3,
} from 'three';

import { occluders } from './anchors';
import {
  boundsShift,
  clampScale,
  pickPoint,
  type Pose,
  rayAtHeight,
  releaseVelocity,
  wheelScale,
  zoomAbout,
} from './mapGestures';

const { ACTION } = CameraControlsImpl;

/** Easing of wheel and double-click zooms: quick, but never a jump. */
export const GESTURE_SMOOTH_S = 0.25;
/** A press becomes a pan once the pointer has moved this far (CSS px). */
const DRAG_SLOP_PX = 3;
/** Wheel events this close together (ms) are one gesture on one level. */
const WHEEL_GESTURE_MS = 220;
/** Double-click zooms in this much (Shift or Alt + double-click: out). */
const DOUBLE_CLICK_SCALE = 0.5;
/** A thrown map slows with this time constant (s) and stops below 0.5 m/s. */
const GLIDE_TAU_S = 0.3;
const GLIDE_STOP_M_S = 0.5;
/** Fastest throw, in camera distances per second. */
const GLIDE_MAX = 4;

interface Drag {
  pointerId: number;
  startX: number;
  startY: number;
  /** Started on a DOM marker: its click is swallowed once the map moves. */
  onMarker: boolean;
  /** The grabbed point, held under the cursor; set once the press moves. */
  anchor?: Vector3;
  samples: { t: number; x: number; z: number }[];
}

/**
 * Map-style mouse input on top of the camera controls:
 *
 * - left drag pans, holding the grabbed ground or roof under the cursor, and
 *   a thrown map glides to a stop;
 * - right or middle drag (or Shift/Alt/Ctrl/⌘ + left drag) turns and tilts;
 * - wheel and trackpad pinch zoom towards the point under the cursor;
 * - double-click zooms in there (Shift or Alt + double-click zooms out).
 *
 * Drags and the wheel also work over the DOM markers (`data-map-anchor`); a
 * marker dragged across does not then open. Touch keeps the controls' own
 * gestures. The view's target stays inside `bounds`.
 */
export function MapPointer({
  controls,
  bounds,
  restSmoothTime,
}: {
  controls: RefObject<CameraControls | null>;
  bounds: Box3;
  /** The controls' usual easing, restored once a gesture's zoom settles. */
  restSmoothTime: number;
}) {
  const get = useThree((s) => s.get);
  const glide = useRef(new Vector3());
  /** Where the glide last left the target; anything else moving it stops it. */
  const glidedTo = useRef(new Vector3());
  const boundsRef = useRef(bounds);
  useEffect(() => {
    boundsRef.current = bounds;
  }, [bounds]);

  useEffect(() => {
    const ctl = controls.current;
    if (!ctl) return;
    return attach(
      ctl,
      get(),
      { glide, glidedTo, bounds: boundsRef },
      restSmoothTime,
    );
  }, [controls, get, restSmoothTime]);

  // The glide after a throw, ahead of the controls' own update.
  const position = useRef(new Vector3());
  const target = useRef(new Vector3());
  const shift = useRef(new Vector3());
  useFrame((_, delta) => {
    const v = glide.current;
    const ctl = controls.current;
    if (v.lengthSq() === 0 || !ctl) return;
    const p = ctl.getPosition(position.current, true);
    const t = ctl.getTarget(target.current, true);
    // Something else moved the view (a fit, a picked place): let it.
    if (t.distanceToSquared(glidedTo.current) > 0.01) {
      v.set(0, 0, 0);
      return;
    }
    const step = Math.min(delta, 0.05);
    p.addScaledVector(v, step);
    t.addScaledVector(v, step);
    const edge = boundsShift(t, boundsRef.current, shift.current);
    p.add(edge);
    t.add(edge);
    void ctl.setLookAt(p.x, p.y, p.z, t.x, t.y, t.z, false);
    glidedTo.current.copy(t);
    v.multiplyScalar(Math.exp(-step / GLIDE_TAU_S));
    if (edge.lengthSq() > 0 || v.length() < GLIDE_STOP_M_S) v.set(0, 0, 0);
  }, -2);

  return null;
}

interface Shared {
  glide: RefObject<Vector3>;
  glidedTo: RefObject<Vector3>;
  bounds: RefObject<Box3>;
}

/** Hooks the gestures to the controls and the page; returns the undo. */
function attach(
  ctl: CameraControls,
  { camera, gl, events }: RootState,
  shared: Shared,
  restSmoothTime: number,
): () => void {
  // Where the controls listen: the canvas's wrapper, or the canvas.
  const element =
    (events.connected as HTMLElement | undefined) ?? gl.domElement;
  const canvas = gl.domElement;
  const probe = new PerspectiveCamera();
  const raycaster = new Raycaster();
  const ndc = new Vector2();
  const pose: Pose = { position: new Vector3(), target: new Vector3() };
  const hit = new Vector3();
  const shift = new Vector3();
  let drag: Drag | undefined;
  let lastWheel = -Infinity;
  let wheelLevel: number | undefined;

  const saved = { ...ctl.mouseButtons };
  ctl.mouseButtons.left = ACTION.NONE;
  ctl.mouseButtons.middle = ACTION.ROTATE;
  ctl.mouseButtons.right = ACTION.ROTATE;
  ctl.mouseButtons.wheel = ACTION.NONE;
  const savedCursor = element.style.cursor;
  const setCursor = (cursor: string) => {
    element.style.cursor = cursor;
  };
  setCursor('grab');

  /** The pose the controls are heading to (`end`) or showing now. */
  const readPose = (end: boolean): Pose => {
    ctl.getPosition(pose.position, end);
    ctl.getTarget(pose.target, end);
    return pose;
  };
  /** The ray under a client point, seen from `camera` or from a pose. */
  const rayAt = (x: number, y: number, from: Camera | Pose) => {
    const rect = canvas.getBoundingClientRect();
    ndc.set(
      ((x - rect.left) / rect.width) * 2 - 1,
      -((y - rect.top) / rect.height) * 2 + 1,
    );
    let eye: Camera;
    if ('isCamera' in from) eye = from;
    else {
      // The live projection, view offset included, at the pose's place.
      probe.position.copy(from.position);
      probe.up.copy(camera.up);
      probe.lookAt(from.target);
      probe.updateMatrixWorld();
      probe.projectionMatrix.copy(camera.projectionMatrix);
      probe.projectionMatrixInverse.copy(camera.projectionMatrixInverse);
      eye = probe;
    }
    raycaster.setFromCamera(ndc, eye);
    return raycaster.ray;
  };
  /** Moves the view to `next`, keeping its target inside the bounds. */
  const apply = (next: Pose, animate: boolean) => {
    boundsShift(next.target, shared.bounds.current, shift);
    next.position.add(shift);
    next.target.add(shift);
    const { position: p, target: t } = next;
    void ctl.setLookAt(p.x, p.y, p.z, t.x, t.y, t.z, animate);
  };
  /** Zooms by `scale` about the point under (x, y), easing. */
  const zoomAt = (x: number, y: number, scale: number, level?: number) => {
    const from = readPose(true);
    const ray = rayAt(x, y, from);
    const anchor =
      level === undefined
        ? pickPoint(ray, occluders, hit)
        : rayAtHeight(ray, level, hit);
    const distance = from.position.distanceTo(from.target);
    const s = clampScale(distance, scale, ctl.minDistance, ctl.maxDistance);
    if (Math.abs(s - 1) < 1e-4) return;
    ctl.smoothTime = GESTURE_SMOOTH_S;
    apply(zoomAbout(from, anchor ?? from.target, s), true);
  };
  const isMapTarget = (target: EventTarget | null) =>
    target instanceof Node && element.contains(target);
  const isMarker = (target: EventTarget | null) =>
    target instanceof Element && !!target.closest('[data-map-anchor]');

  const onPointerDown = (event: PointerEvent) => {
    if (event.pointerType !== 'mouse') return;
    const onMap = isMapTarget(event.target);
    const onMarker = !onMap && isMarker(event.target);
    if (!onMap && !onMarker) return;
    shared.glide.current.set(0, 0, 0);
    const modified =
      event.shiftKey || event.altKey || event.ctrlKey || event.metaKey;
    // The controls read the left button's action when the press reaches
    // them, just after this capturing listener.
    ctl.mouseButtons.left =
      event.button === 0 && modified ? ACTION.ROTATE : ACTION.NONE;
    if (event.button !== 0 || modified) {
      if (onMap) setCursor('grabbing');
      return;
    }
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      onMarker,
      samples: [],
    };
  };

  const onPointerMove = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (!drag.anchor) {
      const moved = Math.hypot(
        event.clientX - drag.startX,
        event.clientY - drag.startY,
      );
      if (moved < DRAG_SLOP_PX) return;
      // Grab what is under the cursor now, holding any easing where it is.
      const now = readPose(false);
      void ctl.setLookAt(
        now.position.x,
        now.position.y,
        now.position.z,
        now.target.x,
        now.target.y,
        now.target.z,
        false,
      );
      const anchor = pickPoint(
        rayAt(event.clientX, event.clientY, now),
        occluders,
        new Vector3(),
      );
      if (!anchor) {
        drag = undefined;
        return;
      }
      drag.anchor = anchor;
      setCursor('grabbing');
      return;
    }
    const from = readPose(true);
    const under = rayAtHeight(
      rayAt(event.clientX, event.clientY, from),
      drag.anchor.y,
      hit,
    );
    if (!under) return;
    shift.subVectors(drag.anchor, under).setY(0);
    // Near the horizon a pixel spans kilometres; keep a move to a stride.
    const stride = from.position.distanceTo(from.target) * 2;
    if (shift.length() > stride) shift.setLength(stride);
    from.position.add(shift);
    from.target.add(shift);
    apply(from, false);
    drag.samples.push({
      t: performance.now(),
      x: from.target.x,
      z: from.target.z,
    });
    if (drag.samples.length > 12) drag.samples.shift();
  };

  const onPointerUp = (event: PointerEvent) => {
    if (event.pointerType !== 'mouse') return;
    ctl.mouseButtons.left = ACTION.NONE;
    setCursor('grab');
    if (!drag || event.pointerId !== drag.pointerId) return;
    const { anchor, samples, onMarker } = drag;
    drag = undefined;
    if (!anchor) return;
    const from = readPose(true);
    const v = releaseVelocity(samples, performance.now());
    const fastest = from.position.distanceTo(from.target) * GLIDE_MAX;
    if (v.length() > fastest) v.setLength(fastest);
    shared.glide.current.copy(v);
    shared.glidedTo.current.copy(from.target);
    // The marker the drag began on must not open as it is let go.
    if (onMarker) {
      const swallow = (click: MouseEvent) => {
        click.preventDefault();
        click.stopPropagation();
      };
      window.addEventListener('click', swallow, {
        capture: true,
        once: true,
      });
      setTimeout(() => window.removeEventListener('click', swallow, true), 0);
    }
  };

  const onWheel = (event: WheelEvent) => {
    if (!isMapTarget(event.target) && !isMarker(event.target)) return;
    // Also stops the browser zooming the page on a trackpad pinch.
    event.preventDefault();
    if (!event.deltaY) return;
    shared.glide.current.set(0, 0, 0);
    const now = performance.now();
    // A gesture keeps the level it began on (a roof, or the ground), so
    // the zoom stays steady as the cursor crosses edges mid-scroll.
    if (now - lastWheel > WHEEL_GESTURE_MS) {
      const from = readPose(true);
      const start = pickPoint(
        rayAt(event.clientX, event.clientY, from),
        occluders,
        hit,
      );
      wheelLevel = start?.y;
    }
    lastWheel = now;
    const scale = wheelScale(event.deltaY, event.deltaMode, event.ctrlKey);
    if (wheelLevel === undefined) {
      // Over the sky: zoom on the view's centre.
      const from = readPose(true);
      const distance = from.position.distanceTo(from.target);
      const s = clampScale(distance, scale, ctl.minDistance, ctl.maxDistance);
      ctl.smoothTime = GESTURE_SMOOTH_S;
      apply(zoomAbout(from, from.target, s), true);
      return;
    }
    zoomAt(event.clientX, event.clientY, scale, wheelLevel);
  };

  const onDoubleClick = (event: MouseEvent) => {
    if (!isMapTarget(event.target)) return;
    shared.glide.current.set(0, 0, 0);
    const out = event.shiftKey || event.altKey;
    zoomAt(
      event.clientX,
      event.clientY,
      out ? 1 / DOUBLE_CLICK_SCALE : DOUBLE_CLICK_SCALE,
    );
  };

  const onRest = () => {
    if (ctl.smoothTime === GESTURE_SMOOTH_S) ctl.smoothTime = restSmoothTime;
  };

  const doc = element.ownerDocument;
  doc.addEventListener('pointerdown', onPointerDown, { capture: true });
  doc.addEventListener('pointermove', onPointerMove);
  doc.addEventListener('pointerup', onPointerUp);
  doc.addEventListener('pointercancel', onPointerUp);
  doc.addEventListener('wheel', onWheel, { passive: false });
  element.addEventListener('dblclick', onDoubleClick);
  ctl.addEventListener('rest', onRest);
  return () => {
    doc.removeEventListener('pointerdown', onPointerDown, { capture: true });
    doc.removeEventListener('pointermove', onPointerMove);
    doc.removeEventListener('pointerup', onPointerUp);
    doc.removeEventListener('pointercancel', onPointerUp);
    doc.removeEventListener('wheel', onWheel);
    element.removeEventListener('dblclick', onDoubleClick);
    ctl.removeEventListener('rest', onRest);
    Object.assign(ctl.mouseButtons, saved);
    element.style.cursor = savedCursor;
  };
}
