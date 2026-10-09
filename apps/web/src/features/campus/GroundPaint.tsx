'use client';

import { useEffect, useMemo } from 'react';
import { DoubleSide, MeshStandardMaterial } from 'three';

import { groundColors, layers, OVERLAY } from './constants';
import {
  crossingsOf,
  laneLines,
  MARKING,
  pitchLines,
  zebraGeometry,
} from './groundMarkings';
import { ribbonGeometry } from './ribbon';
import { STREET_LEVEL } from './sunken';
import type { Ground } from './types';

/** Camera distances (m) over which painted lines fade out, near to far. */
const FADE_M = { street: [320, 700], pitch: [520, 1000] } as const;

/**
 * Paint on the ground: zebra crossings where footpaths cross the streets,
 * dashed lane lines on the main roads and the white lines of the pitches.
 * The lines are thinner than a pixel from afar, so they fade out with
 * distance instead of shimmering.
 */
export function GroundPaint({ data }: { data: Ground }) {
  const geometries = useMemo(() => {
    const zebras = zebraGeometry(crossingsOf(data.ways), layers.lift);
    const lanes = ribbonGeometry(laneLines(data.ways), layers.lift);
    const pitches = ribbonGeometry(
      data.areas
        .filter((a) => a.kind === 'pitch')
        .flatMap((a) => pitchLines(a.outline)),
      layers.lift,
    );
    return { zebras, lanes, pitches };
  }, [data]);
  useEffect(
    () => () => {
      geometries.zebras?.dispose();
      geometries.lanes?.dispose();
      geometries.pitches?.dispose();
    },
    [geometries],
  );

  const materials = useMemo(
    () => ({
      zebra: paint(groundColors.marking, FADE_M.street),
      lane: paint(groundColors.marking, FADE_M.street, MARKING.lane),
      pitch: paint(groundColors.pitchLine, FADE_M.pitch),
    }),
    [],
  );
  useEffect(
    () => () => {
      for (const m of Object.values(materials)) m.dispose();
    },
    [materials],
  );

  return (
    <group>
      {geometries.zebras && (
        <mesh
          geometry={geometries.zebras}
          material={materials.zebra}
          renderOrder={layers.markings}
          receiveShadow
        />
      )}
      {geometries.lanes && (
        <mesh
          geometry={geometries.lanes}
          material={materials.lane}
          renderOrder={layers.markings}
          receiveShadow
        />
      )}
      {geometries.pitches && (
        <mesh
          geometry={geometries.pitches}
          material={materials.pitch}
          renderOrder={layers.markings}
          receiveShadow
        />
      )}
    </group>
  );
}

/**
 * Road paint: a flat overlay that fades with distance, dashed along the
 * ribbon's `uv.x` (metres along the line) when `dash` is given.
 */
function paint(
  color: string,
  fade: readonly [number, number],
  dash?: { dash: number; gap: number },
): MeshStandardMaterial {
  const material = new MeshStandardMaterial({
    color,
    roughness: 0.8,
    transparent: true,
    side: DoubleSide,
    ...OVERLAY,
    ...STREET_LEVEL,
  });
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying float vAlong;')
      .replace(
        '#include <begin_vertex>',
        '#include <begin_vertex>\nvAlong = uv.x;',
      );
    const dashed = dash
      ? `{
          float period = ${(dash.dash + dash.gap).toFixed(2)};
          float t = mod(vAlong, period);
          float aa = fwidth(vAlong);
          diffuseColor.a *= 1.0 - smoothstep(${dash.dash.toFixed(2)} - aa, ${dash.dash.toFixed(2)}, t);
        }`
      : '';
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying float vAlong;')
      .replace(
        '#include <color_fragment>',
        `#include <color_fragment>
        diffuseColor.a *= 1.0 - smoothstep(${fade[0].toFixed(1)}, ${fade[1].toFixed(1)}, length(vViewPosition));
        ${dashed}`,
      );
  };
  material.customProgramCacheKey = () =>
    `ground-paint-${fade.join('-')}-${dash ? 'dashed' : 'solid'}`;
  return material;
}
