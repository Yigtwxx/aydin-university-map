'use client';

import { Line } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import { type BufferGeometry, Shape, ShapeGeometry, Vector2 } from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { groundColors, layers, OVERLAY } from './constants';
import { enuToWorld } from './coords';
import { openRing } from './geometry';
import { type RibbonLine, ribbonGeometry } from './ribbon';
import type { Ground } from './types';

type RoadClass = 'major' | 'minor' | 'path';

const MAJOR = new Set([
  'motorway',
  'motorway_link',
  'trunk',
  'trunk_link',
  'primary',
  'primary_link',
  'secondary',
  'secondary_link',
  'busway',
]);
const PATH = new Set([
  'footway',
  'path',
  'pedestrian',
  'steps',
  'cycleway',
  'bridleway',
  'track',
]);

function roadClass(kind: string): RoadClass {
  if (MAJOR.has(kind)) return 'major';
  if (PATH.has(kind)) return 'path';
  return 'minor';
}

/** Casing (outline) width added on each side, in metres. */
const CASING_M: Record<RoadClass, number> = {
  major: 1.6,
  minor: 1.1,
  path: 0.5,
};

/**
 * The map base under the buildings: campus grounds, parking and pitches, then
 * streets and footpaths as cased strips, like a printed city map.
 *
 * Every layer is flat and drawn with `depthWrite: false` in a fixed render
 * order, so overlapping layers never z-fight at a distance.
 */
export function GroundLayer({ data }: { data: Ground }) {
  const areas = useMemo(() => {
    const byKind = new Map<string, BufferGeometry[]>();
    for (const area of data.areas) {
      const ring = openRing(area.outline);
      if (ring.length < 3) continue;
      const geometry = new ShapeGeometry(
        new Shape(ring.map(([e, n]) => new Vector2(e, n))),
      );
      geometry.rotateX(-Math.PI / 2);
      byKind.set(area.kind, [...(byKind.get(area.kind) ?? []), geometry]);
    }
    return [...byKind].map(([kind, parts]) => {
      const geometry = mergeGeometries(parts, false);
      for (const part of parts) part.dispose();
      return { kind, geometry };
    });
  }, [data]);

  const roads = useMemo(() => {
    const lines: Record<RoadClass, RibbonLine[]> = {
      major: [],
      minor: [],
      path: [],
    };
    for (const way of data.ways)
      lines[roadClass(way.kind)].push({ points: way.line, width: way.width_m });
    const build = (cls: RoadClass, casing: boolean) =>
      ribbonGeometry(
        lines[cls].map((l) => ({
          points: l.points,
          width: l.width + (casing ? CASING_M[cls] * 2 : 0),
        })),
        layers.lift,
      );
    return (['path', 'minor', 'major'] as const).map((cls) => ({
      cls,
      casing: build(cls, true),
      fill: build(cls, false),
    }));
  }, [data]);

  const campusOutlines = useMemo(
    () =>
      data.areas
        .filter((a) => a.kind === 'campus')
        .map((a) => a.outline.map(([e, n]) => enuToWorld(e, n, 0.1))),
    [data],
  );

  useEffect(
    () => () => {
      for (const a of areas) a.geometry.dispose();
      for (const r of roads) {
        r.casing?.dispose();
        r.fill?.dispose();
      }
    },
    [areas, roads],
  );

  return (
    <group>
      {areas.map(({ kind, geometry }) => (
        <mesh
          key={kind}
          geometry={geometry}
          position-y={layers.lift}
          renderOrder={layers.areas}
          receiveShadow
        >
          <meshStandardMaterial
            color={
              groundColors.areas[kind as keyof typeof groundColors.areas] ??
              groundColors.areas.pedestrian
            }
            roughness={1}
            {...OVERLAY}
          />
        </mesh>
      ))}
      {roads.map(
        ({ cls, casing }) =>
          casing && (
            <mesh
              key={`${cls}-casing`}
              geometry={casing}
              renderOrder={layers.casing}
              receiveShadow
            >
              <meshStandardMaterial
                color={groundColors.casing[cls]}
                roughness={1}
                {...OVERLAY}
              />
            </mesh>
          ),
      )}
      {roads.map(
        ({ cls, fill }) =>
          fill && (
            <mesh
              key={`${cls}-fill`}
              geometry={fill}
              renderOrder={
                layers.roads + (cls === 'major' ? 2 : cls === 'minor' ? 1 : 0)
              }
              receiveShadow
            >
              <meshStandardMaterial
                color={groundColors.fill[cls]}
                roughness={0.95}
                {...OVERLAY}
              />
            </mesh>
          ),
      )}
      {campusOutlines.map((points, i) => (
        <Line
          key={i}
          points={points}
          color={groundColors.campusOutline}
          lineWidth={2}
          dashed
          dashSize={6}
          gapSize={4}
          transparent
          opacity={0.75}
          depthWrite={false}
          renderOrder={layers.outline}
        />
      ))}
    </group>
  );
}
