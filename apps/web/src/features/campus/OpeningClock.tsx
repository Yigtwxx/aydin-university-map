'use client';

import { useFrame } from '@react-three/fiber';
import { useEffect, useRef, useState } from 'react';

import { INTRO, INTRO_OVER, introClock, introLight } from './opening';

/** Fast-forward once the visitor touches, scrolls or presses a key. */
const SKIP_SPEED = 4;
/** Frames to wait before the clock runs: shaders compile in the first ones. */
const WARMUP_FRAMES = 3;
/** Longest step of one frame (s): a hitch skips a little, never the rest. */
const MAX_STEP_S = 0.1;
/**
 * If frames stall (a background tab, a lost WebGL context, a very slow GPU),
 * the opening ends by wall clock this long after it should have.
 */
const WATCHDOG_S = 4;

/** Development only: `?openingAt=1.4` holds the opening at 1.4 s for review. */
function heldAt(): number | undefined {
  if (process.env.NODE_ENV === 'production') return undefined;
  const value = new URLSearchParams(window.location.search).get('openingAt');
  return value === null ? undefined : Number(value);
}

interface OpeningClockProps {
  /** Time for the camera to tilt into the 3D view. */
  onGlide: () => void;
  /** Time for the panel and controls. */
  onReveal: () => void;
  /** Every building stands: unmount the opening. */
  onDone: () => void;
}

/**
 * Plays the opening (opening.ts): advances the shared clock that the massing
 * and the grade read, and calls back at its milestones. Draws nothing.
 */
export function OpeningClock({ onGlide, onReveal, onDone }: OpeningClockProps) {
  const frames = useRef(0);
  const speed = useRef(1);
  const fired = useRef({ glide: false, reveal: false, done: false });
  const [held] = useState(heldAt);

  // Stalled frames must never leave the map without its panel: finish by
  // the wall clock, with every building standing.
  useEffect(() => {
    // A held opening (review in development) stays where it is.
    if (held !== undefined) return;
    const id = window.setTimeout(
      () => {
        const f = fired.current;
        introClock.time.value = INTRO_OVER;
        introClock.light.value = 1;
        if (!f.glide) onGlide();
        if (!f.reveal) onReveal();
        if (!f.done) onDone();
        fired.current = { glide: true, reveal: true, done: true };
      },
      (INTRO.doneS + WATCHDOG_S) * 1000,
    );
    return () => window.clearTimeout(id);
    // Started once, when the opening starts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [held]);

  // Any touch, scroll or key: play the rest quickly instead of cutting.
  useEffect(() => {
    const skip = () => {
      speed.current = SKIP_SPEED;
    };
    const options = { passive: true } as const;
    window.addEventListener('pointerdown', skip, options);
    window.addEventListener('wheel', skip, options);
    window.addEventListener('keydown', skip);
    return () => {
      window.removeEventListener('pointerdown', skip);
      window.removeEventListener('wheel', skip);
      window.removeEventListener('keydown', skip);
    };
  }, []);

  useFrame((_, delta) => {
    if (frames.current < WARMUP_FRAMES) {
      frames.current++;
      return;
    }
    // A long frame (tab switch, a hitch) must not jump the animation.
    const t =
      held ??
      introClock.time.value + Math.min(delta, MAX_STEP_S) * speed.current;
    introClock.time.value = t;
    introClock.light.value = introLight(t);
    const f = fired.current;
    if (!f.glide && t >= INTRO.glideS) {
      f.glide = true;
      onGlide();
    }
    if (!f.reveal && t >= INTRO.revealS) {
      f.reveal = true;
      onReveal();
    }
    if (!f.done && t >= INTRO.doneS) {
      f.done = true;
      introClock.time.value = INTRO_OVER;
      introClock.light.value = 1;
      onDone();
    }
  });

  return null;
}
