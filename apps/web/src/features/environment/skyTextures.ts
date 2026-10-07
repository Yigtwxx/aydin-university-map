'use client';

import { useEffect, useState } from 'react';

import { tileableNoise } from './skyNoise';

/**
 * Cloud and fog textures for the weather sheet: the shape in the alpha,
 * tileable horizontally so a layer drifts by sliding one copy into the next.
 * Clouds are lit from above: white where the density falls off upward (their
 * sunlit tops), blue-grey where it falls off downward (their undersides).
 * Drawn once per visit, off the first frame, and kept as blob URLs.
 */
export type SkyTexture = 'cumulus' | 'stratus' | 'fog';

const WIDTH = 384;
const HEIGHT = 192;

/** Noise, the band of it that becomes visible, and whether it is lit. */
const RECIPES: Record<
  SkyTexture,
  {
    cellsX: number;
    cellsY: number;
    seed: number;
    from: number;
    to: number;
    lit: boolean;
  }
> = {
  // Separate puffs with blue between.
  cumulus: { cellsX: 4, cellsY: 2, seed: 11, from: 0.55, to: 0.64, lit: true },
  // A broken deck that covers most of the sky.
  stratus: { cellsX: 4, cellsY: 2, seed: 23, from: 0.34, to: 0.7, lit: true },
  // Long, soft wisps; fog has no tops or undersides.
  fog: { cellsX: 2, cellsY: 4, seed: 7, from: 0.42, to: 0.74, lit: false },
};

/** Underside colour of a lit cloud. */
const SHADE = [148, 162, 184] as const;
/** How far up the lighting looks for the cloud's edge, in texture px. */
const LIGHT_REACH = 5;
/** How strongly a density step brightens or shades. */
const LIGHT_GAIN = 7;

function smoothstep(from: number, to: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - from) / (to - from)));
  return t * t * (3 - 2 * t);
}

async function draw(name: SkyTexture): Promise<string> {
  // Let the sheet open first; the texture fades in a moment later.
  await new Promise((resolve) => setTimeout(resolve, 0));
  const { cellsX, cellsY, seed, from, to, lit } = RECIPES[name];
  const noise = tileableNoise({
    width: WIDTH,
    height: HEIGHT,
    cellsX,
    cellsY,
    octaves: 5,
    seed,
  });
  const density = noise.map((n) => smoothstep(from, to, n));
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y++) {
    // The texture tiles vertically too, so look up across the top edge.
    const above = ((y - LIGHT_REACH + HEIGHT) % HEIGHT) * WIDTH;
    for (let x = 0; x < WIDTH; x++) {
      const i = y * WIDTH + x;
      // Thinner above than here: a top, facing the sun.
      const light = lit
        ? Math.min(
            1,
            Math.max(
              0,
              0.55 + (density[i]! - density[above + x]!) * LIGHT_GAIN,
            ),
          )
        : 1;
      pixels[i * 4] = SHADE[0] + (255 - SHADE[0]) * light;
      pixels[i * 4 + 1] = SHADE[1] + (255 - SHADE[1]) * light;
      pixels[i * 4 + 2] = SHADE[2] + (255 - SHADE[2]) * light;
      pixels[i * 4 + 3] = Math.round(density[i]! * 255);
    }
  }
  const canvas = document.createElement('canvas');
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  canvas
    .getContext('2d')
    ?.putImageData(new ImageData(pixels, WIDTH, HEIGHT), 0, 0);
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve),
  );
  if (!blob) throw new Error(`could not draw the ${name} texture`);
  return URL.createObjectURL(blob);
}

const drawn = new Map<SkyTexture, Promise<string>>();

function textureUrl(name: SkyTexture): Promise<string> {
  let url = drawn.get(name);
  if (!url) {
    url = draw(name);
    drawn.set(name, url);
  }
  return url;
}

/** The texture's URL once drawn; `undefined` while drawing or when not asked. */
export function useSkyTexture(
  name: SkyTexture | undefined,
): string | undefined {
  const [ready, setReady] = useState<{ name: SkyTexture; url: string }>();
  useEffect(() => {
    if (!name) return;
    let current = true;
    textureUrl(name).then(
      (url) => {
        if (current) setReady({ name, url });
      },
      // Decoration only: without the texture the sky is just plainer.
      () => {},
    );
    return () => {
      current = false;
    };
  }, [name]);
  if (!name || ready?.name !== name) return undefined;
  return ready.url;
}
