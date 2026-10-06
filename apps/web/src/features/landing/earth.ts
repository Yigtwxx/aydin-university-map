'use client';

import { useEffect, useState } from 'react';
import {
  LinearFilter,
  LinearMipmapLinearFilter,
  NearestFilter,
  NoColorSpace,
  SRGBColorSpace,
  type Texture,
  TextureLoader,
} from 'three';

/** data/out/earth/earth.json (pipeline: amap export earth). */
export interface EarthManifest {
  version: number;
  crs: string;
  origin: { lat: number; lng: number };
  levels: {
    id: string;
    centre: [number, number];
    size_m: number;
    day: { file: string; px: number };
    night: { file: string; px: number };
    height: { file: string; px: number; encoding: 'terrarium' };
    water: { file: string; px: number; shore_max_m: number };
  }[];
  height_range_m: [number, number];
  attribution: string[];
}

export interface EarthLevel {
  /** centre east, centre north, size (m), height texture px */
  frame: [number, number, number, number];
  day: Texture;
  night: Texture;
  height: Texture;
  water: Texture;
  shoreMax: number;
}

export interface Earth {
  manifest: EarthManifest;
  /** Loaded levels, coarse first; finer ones arrive later. */
  levels: EarthLevel[];
  /** Terrain height (m) under the campus origin, so the campus sits at 0. */
  originHeight: number;
}

const loader = new TextureLoader();

function load(url: string): Promise<Texture> {
  return new Promise((resolve, reject) =>
    loader.load(url, resolve, undefined, () =>
      reject(new Error(`could not load ${url}`)),
    ),
  );
}

/** Terrarium RGB -> metres. */
export function terrarium(r: number, g: number, b: number): number {
  return r * 256 + g + b / 256 - 32768;
}

/** Height (m) of a level's terrain at the campus origin, read on the CPU. */
function heightAtOrigin(texture: Texture, frame: EarthLevel['frame']): number {
  const image = texture.image as HTMLImageElement;
  const [cx, cy, size] = frame;
  const u = (0 - cx) / size + 0.5;
  const v = (0 - cy) / size + 0.5;
  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext('2d');
  if (!ctx) return 0;
  // Row 0 of the image is the north edge.
  const x = Math.min(image.width - 1, Math.floor(u * image.width));
  const y = Math.min(image.height - 1, Math.floor((1 - v) * image.height));
  ctx.drawImage(image, x, y, 1, 1, 0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return terrarium(r ?? 0, g ?? 0, b ?? 0);
}

async function loadLevel(
  base: string,
  level: EarthManifest['levels'][number],
  anisotropy: number,
): Promise<EarthLevel> {
  const [day, night, height, water] = await Promise.all([
    load(`${base}/${level.day.file}`),
    load(`${base}/${level.night.file}`),
    load(`${base}/${level.height.file}`),
    load(`${base}/${level.water.file}`),
  ]);
  for (const t of [day, night]) {
    t.colorSpace = SRGBColorSpace;
    t.minFilter = LinearMipmapLinearFilter;
    t.anisotropy = anisotropy;
  }
  // Encoded heights are decoded per texel in the shader: no filtering.
  height.colorSpace = NoColorSpace;
  height.minFilter = NearestFilter;
  height.magFilter = NearestFilter;
  height.generateMipmaps = false;
  water.colorSpace = NoColorSpace;
  water.minFilter = LinearMipmapLinearFilter;
  water.magFilter = LinearFilter;
  return {
    frame: [level.centre[0], level.centre[1], level.size_m, level.height.px],
    day,
    night,
    height,
    water,
    shoreMax: level.water.shore_max_m,
  };
}

/**
 * The earth textures under ``base``: the manifest, then one level at a time
 * from coarse to fine, so the first frame can draw as soon as the region is in.
 */
export function useEarth(base: string, anisotropy = 8): Earth | undefined {
  const [earth, setEarth] = useState<Earth>();
  useEffect(() => {
    let cancelled = false;
    const owned: Texture[] = [];
    (async () => {
      const response = await fetch(`${base}/earth.json`);
      if (!response.ok) throw new Error(`earth.json: HTTP ${response.status}`);
      const manifest = (await response.json()) as EarthManifest;
      // Largest first: the region draws before the city and Florya details.
      const ordered = [...manifest.levels].sort((a, b) => b.size_m - a.size_m);
      const levels: EarthLevel[] = [];
      let originHeight = 0;
      for (const spec of ordered) {
        // One retry (a level can be mid-upload); a level that still fails is
        // skipped, the coarser ones already cover the view.
        let level: EarthLevel | undefined;
        for (let attempt = 0; attempt < 2 && !level; attempt++) {
          try {
            level = await loadLevel(base, spec, anisotropy);
          } catch (error) {
            if (attempt === 0) await new Promise((r) => setTimeout(r, 1500));
            else console.warn(`earth level ${spec.id} skipped:`, error);
          }
        }
        if (cancelled) return;
        if (!level) continue;
        owned.push(level.day, level.night, level.height, level.water);
        levels.push(level);
        // The finest level loaded so far knows the ground under the campus.
        originHeight = heightAtOrigin(level.height, level.frame);
        setEarth({ manifest, levels: [...levels], originHeight });
      }
    })().catch((error: unknown) => {
      // Without the manifest the landing keeps its sky and clouds.
      console.warn('earth unavailable:', error);
    });
    return () => {
      cancelled = true;
      for (const t of owned) t.dispose();
    };
  }, [base, anisotropy]);
  return earth;
}
