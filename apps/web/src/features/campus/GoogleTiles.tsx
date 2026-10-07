'use client';

import { useFrame } from '@react-three/fiber';
import {
  CesiumIonAuthPlugin,
  GLTFExtensionsPlugin,
  ReorientationPlugin,
  TileCompressionPlugin,
  TilesFadePlugin,
} from '3d-tiles-renderer/plugins';
import { TilesPlugin, TilesRenderer } from '3d-tiles-renderer/r3f';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { TilesRenderer as TilesRendererImpl } from '3d-tiles-renderer/three';
import { type Group, Raycaster, Vector3 } from 'three';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';

import { CAMPUS_LAT, CAMPUS_LNG } from './constants';

/** Cesium ion asset id of Google Photorealistic 3D Tiles. */
const GOOGLE_3D_TILES = 2275207;
const DEG = Math.PI / 180;
/**
 * The tiles frame has +X west and +Z true north; the map's world has +X east,
 * +Z south and grid north (UTM 35N), which at the campus lies 1.179° east of
 * true north. Half a turn plus the convergence lines them up.
 */
const YAW = Math.PI + 1.1791 * DEG;
/** Ground probes around the origin; the lowest hit is the street, not a roof. */
const PROBES = [
  [0, 0],
  [45, 0],
  [-45, 0],
  [0, 45],
  [0, -45],
].map(([x, z]) => new Vector3(x, 3000, z));
const DOWN = new Vector3(0, -1, 0);

/** One credit line: text, or a logo image (https only). */
export interface Credit {
  text?: string;
  image?: string;
}

/**
 * Attributions arrive as plain strings or as small HTML snippets (a linked
 * logo). Keep only text and https images, never the markup itself.
 */
export function toCredits(
  attributions: { type: string; value: unknown }[],
): Credit[] {
  const credits: Credit[] = [];
  const seen = new Set<string>();
  const add = (credit: Credit) => {
    const key = credit.image ?? credit.text ?? '';
    if (!key || seen.has(key)) return;
    seen.add(key);
    credits.push(credit);
  };
  for (const { type, value } of attributions) {
    if (type === 'string' && typeof value === 'string') add({ text: value });
    else if (
      type === 'image' &&
      typeof value === 'string' &&
      value.startsWith('https://')
    )
      add({ image: value });
    else if (type === 'html' && typeof value === 'string') {
      const doc = new DOMParser().parseFromString(value, 'text/html');
      for (const img of doc.querySelectorAll('img')) {
        if (img.src.startsWith('https://')) add({ image: img.src });
      }
      const text = doc.body.textContent?.trim();
      if (text) add({ text });
    }
  }
  return credits;
}

/**
 * Google's photorealistic İstanbul, streamed through Cesium ion and aligned
 * with the campus frame (ground under the campus origin at y = 0).
 */
export function GoogleTiles({
  token,
  errorTarget,
  onFailure,
  onReady,
  onAttributions,
}: {
  token: string;
  /** Screen-space error in px: lower is sharper and heavier. */
  errorTarget: number;
  onFailure: () => void;
  /** First time the view has fully loaded. */
  onReady: () => void;
  /** Credits of the tiles in view (Google requires them on screen). */
  onAttributions: (credits: Credit[]) => void;
}) {
  const draco = useMemo(() => {
    const loader = new DRACOLoader();
    loader.setDecoderPath('/draco/');
    return loader;
  }, []);
  useEffect(
    () => () => {
      draco.dispose();
    },
    [draco],
  );

  const renderer = useRef<TilesRendererImpl>(null);
  // The R3F wrapper compares plugin args one level deep: arrays rebuilt on
  // every render would recreate (and re-authenticate) the plugins each time.
  const ionArgs = useMemo(
    () => [
      { apiToken: token, assetId: GOOGLE_3D_TILES, autoRefreshToken: true },
    ],
    [token],
  );
  const gltfArgs = useMemo(() => [{ dracoLoader: draco }], [draco]);
  const fadeArgs = useMemo(() => [{ fadeDuration: 400 }], []);
  const orientArgs = useMemo(
    () => [{ lat: CAMPUS_LAT * DEG, lon: CAMPUS_LNG * DEG, height: 0 }],
    [],
  );
  const lift = useRef<Group>(null);
  const [ready, setReady] = useState(false);
  const probe = useRef(new Raycaster());
  const lastProbe = useRef(0);
  const lastCredits = useRef('');

  // Keep the campus ground at y = 0: measure the tiles around the origin as
  // finer levels arrive, and ease towards it so nothing visibly jumps.
  useFrame(({ clock }) => {
    const group = renderer.current?.group;
    const offset = lift.current;
    if (!group || !offset || clock.elapsedTime - lastProbe.current < 0.4)
      return;
    lastProbe.current = clock.elapsedTime;
    let ground = Infinity;
    for (const origin of PROBES) {
      const ray = probe.current;
      ray.set(origin, DOWN);
      ray.far = 12000;
      const hit = ray.intersectObject(group, true)[0];
      if (hit) ground = Math.min(ground, hit.point.y);
    }
    if (Number.isFinite(ground)) offset.position.y -= ground * 0.5;
  });

  // Credits change with the tiles in view; collect them a few times a second.
  useEffect(() => {
    const tilesRenderer = renderer.current;
    if (!tilesRenderer) return;
    let queued = false;
    const collect = () => {
      if (queued) return;
      queued = true;
      setTimeout(() => {
        queued = false;
        const credits = toCredits(tilesRenderer.getAttributions());
        const key = JSON.stringify(credits);
        if (key === lastCredits.current) return;
        lastCredits.current = key;
        onAttributions(credits);
      }, 300);
    };
    tilesRenderer.addEventListener('tile-visibility-change', collect);
    tilesRenderer.addEventListener('load-tileset', collect);
    collect();
    return () => {
      tilesRenderer.removeEventListener('tile-visibility-change', collect);
      tilesRenderer.removeEventListener('load-tileset', collect);
    };
  }, [ready, onAttributions]);

  return (
    <group ref={lift}>
      <group rotation-y={YAW}>
        <TilesRenderer
          ref={renderer}
          errorTarget={errorTarget}
          onLoadError={onFailure}
          onTilesLoadEnd={() => {
            if (!ready) {
              setReady(true);
              onReady();
            }
          }}
        >
          <TilesPlugin plugin={CesiumIonAuthPlugin} args={ionArgs} />
          <TilesPlugin plugin={GLTFExtensionsPlugin} args={gltfArgs} />
          <TilesPlugin plugin={TileCompressionPlugin} />
          <TilesPlugin plugin={TilesFadePlugin} args={fadeArgs} />
          <TilesPlugin plugin={ReorientationPlugin} args={orientArgs} />
        </TilesRenderer>
      </group>
    </group>
  );
}
