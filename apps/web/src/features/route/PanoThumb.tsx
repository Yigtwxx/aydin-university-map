'use client';

import { cn } from 'cn';
import { type ReactNode, useState } from 'react';

import { yawForBearing } from '@/features/campus/coords';
import { panoFaceUrl } from '@/lib/assets';

export type CubeFace = 'f' | 'r' | 'b' | 'l';

const FACES: readonly CubeFace[] = ['f', 'r', 'b', 'l'];

/** The side cube face that looks closest to a compass bearing. */
export function faceTowards(
  bearingDegrees: number,
  headingDegrees: number,
): CubeFace {
  const quarter = yawForBearing(bearingDegrees, headingDegrees) / (Math.PI / 2);
  return FACES[Math.round(quarter) % 4] ?? 'f';
}

/**
 * A small, real view from a 360° spot: one 384 px cube face, lazy loaded.
 * Until it arrives (or if it never does) the fallback shows instead, so the
 * tile keeps its size and never flashes a broken image.
 */
export function PanoThumb({
  scene,
  face = 'f',
  fallback,
  className,
  children,
}: {
  scene: string;
  face?: CubeFace;
  fallback?: ReactNode;
  className?: string;
  /** Overlays (badges, labels) drawn above the photo. */
  children?: ReactNode;
}) {
  const src = panoFaceUrl(scene, face, true);
  // Keyed by URL, so a new scene starts hidden again without an effect.
  const [state, setState] = useState<{
    src: string;
    status: 'loaded' | 'failed';
  }>();
  const status = state?.src === src ? state.status : 'loading';

  return (
    <span
      className={cn(
        'relative isolate block overflow-hidden bg-fill-strong',
        // A hairline drawn over the photo keeps bright skies from bleeding
        // into the panel.
        'after:pointer-events-none after:absolute after:inset-0 after:rounded-[inherit] after:shadow-[inset_0_0_0_1px_rgb(0_0_0/0.07)]',
        className,
      )}
    >
      {status !== 'loaded' && fallback && (
        <span className="absolute inset-0 flex items-center justify-center">
          {fallback}
        </span>
      )}
      {status !== 'failed' && (
        // Pre-sized 384 px WebP faces from the asset host; next/image would
        // only re-encode them and needs the host whitelisted per deployment.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setState({ src, status: 'loaded' })}
          onError={() => setState({ src, status: 'failed' })}
          className={cn(
            'absolute inset-0 size-full object-cover transition-[opacity,transform] duration-250 ease-out-soft',
            status === 'loaded' ? 'opacity-100' : 'opacity-0',
          )}
        />
      )}
      {children}
    </span>
  );
}
