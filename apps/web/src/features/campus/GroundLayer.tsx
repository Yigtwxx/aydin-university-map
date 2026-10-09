'use client';

import { Line } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import {
  type BufferGeometry,
  MeshStandardMaterial,
  Shape,
  ShapeGeometry,
  Vector2,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { liftOntoTerraces } from './clip';
import { GroundPaint } from './GroundPaint';
import { type RoadClass, roadClass } from './groundMarkings';
import { groundColors, layers, OVERLAY } from './constants';
import { enuToWorld } from './coords';
import { openRing } from './geometry';
import { patchPaving } from './paving';
import { useTerrain } from './queries';
import { type RibbonLine, ribbonGeometry } from './ribbon';
import {
  OPENING_LIFT_M,
  OPENING_MASK,
  OPENING_ORDER,
  STREET_LEVEL,
  sunkenOpenings,
} from './sunken';
import type { Terrain } from './terrain';
import type { Ground } from './types';

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
 *
 * Terraces (StreetFurniture) stand on the street-level layers and hide them;
 * the parts of each layer that lie on a terrace are drawn again on its top,
 * in the same order, so paths and paving carry on up there.
 */
export function GroundLayer({ data }: { data: Ground }) {
  const terrain = useTerrain();
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

  const raised = useMemo(() => {
    if (terrain.terraces.length === 0) return undefined;
    const lift = (geometry: BufferGeometry | undefined) =>
      geometry && liftOntoTerraces(geometry, terrain.terraces, layers.lift);
    return {
      areas: areas.flatMap(({ kind, geometry }) => {
        const lifted = lift(geometry);
        return lifted ? [{ kind, geometry: lifted }] : [];
      }),
      roads: roads.map(({ cls, casing, fill }) => ({
        cls,
        casing: lift(casing),
        fill: lift(fill),
      })),
    };
  }, [areas, roads, terrain]);

  const campusOutlines = useMemo(
    () =>
      data.areas
        .filter((a) => a.kind === 'campus')
        .map((a) => drape(a.outline, terrain, 0.1)),
    [data, terrain],
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
  useEffect(
    () => () => {
      for (const a of raised?.areas ?? []) a.geometry.dispose();
      for (const r of raised?.roads ?? []) {
        r.casing?.dispose();
        r.fill?.dispose();
      }
    },
    [raised],
  );

  return (
    <group>
      <SunkenOpenings terrain={terrain} />
      <FlatLayers
        areas={areas}
        roads={roads}
        areaLift={layers.lift}
        streetLevel
      />
      <GroundPaint data={data} />
      {raised && (
        <FlatLayers areas={raised.areas} roads={raised.roads} areaLift={0} />
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

/**
 * A polyline laid on the terrain: densified every 2 m so it follows level
 * changes, `up` metres above the ground.
 */
function drape(
  line: [number, number][],
  terrain: Terrain,
  up: number,
): [number, number, number][] {
  if (terrain.flat) return line.map(([e, n]) => enuToWorld(e, n, up));
  const out: [number, number, number][] = [];
  line.forEach(([e, n], i) => {
    const prev = line[i - 1];
    if (prev) {
      const steps = Math.floor(Math.hypot(e - prev[0], n - prev[1]) / 2);
      for (let k = 1; k < steps; k++) {
        const pe = prev[0] + ((e - prev[0]) * k) / steps;
        const pn = prev[1] + ((n - prev[1]) * k) / steps;
        out.push(enuToWorld(pe, pn, terrain.heightAt(pe, pn) + up));
      }
    }
    out.push(enuToWorld(e, n, terrain.heightAt(e, n) + up));
  });
  return out;
}

/** Areas, then road casings, then road fills, in the fixed layer order. */
function FlatLayers({
  areas,
  roads,
  areaLift,
  streetLevel = false,
}: {
  areas: { kind: string; geometry: BufferGeometry }[];
  roads: {
    cls: RoadClass;
    casing: BufferGeometry | undefined;
    fill: BufferGeometry | undefined;
  }[];
  /** Height the area geometry is drawn at (0 when already baked in). */
  areaLift: number;
  /** At the street datum: hidden over a sunken terrace's opening. */
  streetLevel?: boolean;
}) {
  const stencil = streetLevel ? STREET_LEVEL : {};
  return (
    <>
      {areas.map(({ kind, geometry }) =>
        !streetLevel && PAVED_AREAS.has(kind) ? (
          <PavedArea key={kind} kind={kind} geometry={geometry} />
        ) : (
          <mesh
            key={kind}
            geometry={geometry}
            position-y={areaLift}
            renderOrder={layers.areas}
            receiveShadow
          >
            <meshStandardMaterial
              color={areaColor(kind)}
              roughness={1}
              {...OVERLAY}
              {...stencil}
            />
          </mesh>
        ),
      )}
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
                {...stencil}
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
                {...stencil}
              />
            </mesh>
          ),
      )}
    </>
  );
}

/** Grounds whose part on a terrace shows the terrace's paving. */
const PAVED_AREAS: ReadonlySet<string> = new Set(['campus', 'pedestrian']);

const areaColor = (kind: string) =>
  groundColors.areas[kind as keyof typeof groundColors.areas] ??
  groundColors.areas.pedestrian;

/**
 * Campus grounds lifted onto a terrace, laid in that terrace's paving: setts,
 * or the fan cobbles on the plaza (`paving` attribute from liftOntoTerraces).
 */
function PavedArea({
  kind,
  geometry,
}: {
  kind: string;
  geometry: BufferGeometry;
}) {
  const material = useMemo(() => {
    const m = new MeshStandardMaterial({
      color: areaColor(kind),
      roughness: 1,
      ...OVERLAY,
    });
    patchPaving(m);
    return m;
  }, [kind]);
  useEffect(() => () => material.dispose(), [material]);
  return (
    <mesh
      geometry={geometry}
      material={material}
      renderOrder={layers.areas}
      receiveShadow
    />
  );
}

/** Invisible lids over terraces sunk below the street, drawn into the stencil. */
function SunkenOpenings({ terrain }: { terrain: Terrain }) {
  const geometry = useMemo(() => {
    const rings = sunkenOpenings(terrain.terraces);
    if (rings.length === 0) return undefined;
    const g = new ShapeGeometry(
      rings.map((r) => new Shape(r.map(([e, n]) => new Vector2(e, n)))),
    );
    g.rotateX(-Math.PI / 2);
    return g;
  }, [terrain]);
  useEffect(() => () => geometry?.dispose(), [geometry]);
  if (!geometry) return null;
  return (
    <mesh
      geometry={geometry}
      position-y={OPENING_LIFT_M}
      renderOrder={OPENING_ORDER}
    >
      <meshBasicMaterial {...OPENING_MASK} />
    </mesh>
  );
}
