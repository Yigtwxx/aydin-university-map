'use client';

import { useEffect, useRef } from 'react';

import {
  createField,
  DEPTHS,
  type Field,
  LAYERS,
  type PrecipitationKind,
  resizeField,
  slantAt,
  stepField,
} from './precipitationField';

/** Rain is faintly blue, like the drops in the 3D scene. */
const RAIN = '214 228 255';

/** A soft round flake, drawn once and scaled per particle. */
function flakeSprite(): HTMLCanvasElement {
  const size = 32;
  const sprite = document.createElement('canvas');
  sprite.width = size;
  sprite.height = size;
  const ctx = sprite.getContext('2d');
  if (ctx) {
    const glow = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
    glow.addColorStop(0, 'rgb(255 255 255 / 1)');
    glow.addColorStop(0.45, 'rgb(255 255 255 / 0.85)');
    glow.addColorStop(1, 'rgb(255 255 255 / 0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, size, size);
  }
  return sprite;
}

/**
 * Rain streaks fade from tail to head. Each depth is drawn as two batched
 * paths (a faint tail half, a brighter head half), so a downpour costs six
 * strokes a frame however many drops there are.
 */
function drawRain(ctx: CanvasRenderingContext2D, field: Field, t: number) {
  const slant = slantAt(field, t);
  ctx.lineCap = 'round';
  for (let layer = 0; layer < LAYERS; layer++) {
    const depth = DEPTHS.rain[layer]!;
    ctx.lineWidth = 0.6 + layer * 0.35;
    for (const [from, to, alpha] of [
      [1, 0.5, depth.alpha * 0.35],
      [0.5, 0, depth.alpha],
    ] as const) {
      ctx.strokeStyle = `rgb(${RAIN} / ${alpha})`;
      ctx.beginPath();
      for (const p of field.particles) {
        if (p.layer !== layer) continue;
        const length = depth.size * p.jitter;
        ctx.moveTo(p.x - slant * length * from, p.y - length * from);
        ctx.lineTo(p.x - slant * length * to, p.y - length * to);
      }
      ctx.stroke();
    }
  }
}

function drawSnow(
  ctx: CanvasRenderingContext2D,
  field: Field,
  sprite: HTMLCanvasElement,
) {
  for (const p of field.particles) {
    const depth = DEPTHS.snow[p.layer]!;
    const size = depth.size * p.jitter * 2.6;
    ctx.globalAlpha = depth.alpha;
    ctx.drawImage(sprite, p.x - size / 2, p.y - size / 2, size, size);
  }
  ctx.globalAlpha = 1;
}

/**
 * Falling rain or snow over the weather sheet's sky. Decorative; under
 * reduced motion it draws one still frame.
 */
export function Precipitation({
  kind,
  intensity,
  wind,
}: {
  kind: PrecipitationKind;
  intensity: number;
  wind: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvas.current;
    const ctx = element?.getContext('2d');
    if (!element || !ctx) return;
    const field = createField(kind, intensity, wind);
    const sprite = kind === 'snow' ? flakeSprite() : undefined;
    const draw = (t: number) => {
      ctx.clearRect(0, 0, field.width, field.height);
      if (sprite) drawSnow(ctx, field, sprite);
      else drawRain(ctx, field, t);
    };

    const resize = () => {
      const { width, height } = element.getBoundingClientRect();
      const scale = Math.min(window.devicePixelRatio || 1, 2);
      element.width = Math.round(width * scale);
      element.height = Math.round(height * scale);
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      resizeField(field, width, height);
      draw(performance.now() / 1000);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches)
      return () => observer.disconnect();

    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      // A long gap (a background tab) resumes calmly instead of jumping.
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      stepField(field, dt, now / 1000);
      draw(now / 1000);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [kind, intensity, wind]);

  return (
    <canvas
      ref={canvas}
      aria-hidden
      className="pointer-events-none absolute inset-0 size-full"
    />
  );
}
