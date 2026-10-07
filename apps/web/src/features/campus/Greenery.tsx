'use client';

import { useEffect, useMemo, useRef } from 'react';
import {
  Color,
  type InstancedMesh,
  Object3D,
  Shape,
  ShapeGeometry,
  Vector2,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { liftOntoTerraces } from './clip';
import { layers, OVERLAY } from './constants';
import { enuToWorld } from './coords';
import { openRing } from './geometry';
import { useTerrain } from './queries';
import type { Terrain } from './terrain';
import type { Greenery as GreeneryData } from './types';

const AREA_COLORS: Record<string, string> = {
  pitch: '#6FA85A',
  park: '#8DB36B',
  garden: '#8DB36B',
};
const GRASS = '#9DBE78';
const CANOPY = '#5F8F4E';
const TRUNK = '#6E5A44';

/** Stable pseudo-random value per tree so sizes don't change between renders. */
function hash(i: number): number {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

export function Greenery({ data }: { data: GreeneryData }) {
  const terrain = useTerrain();
  const areas = useMemo(() => {
    const byColor = new Map<string, ShapeGeometry[]>();
    for (const area of data.areas) {
      const ring = openRing(area.outline);
      if (ring.length < 3) continue;
      const geometry = new ShapeGeometry(
        new Shape(ring.map(([e, n]) => new Vector2(e, n))),
      );
      geometry.rotateX(-Math.PI / 2);
      const color = AREA_COLORS[area.kind] ?? GRASS;
      byColor.set(color, [...(byColor.get(color) ?? []), geometry]);
    }
    return [...byColor].map(([color, parts]) => ({
      color,
      geometry: mergeGeometries(parts, false),
    }));
  }, [data]);
  useEffect(() => () => areas.forEach((a) => a.geometry.dispose()), [areas]);
  // Lawns on terraces: the same areas again on each terrace's top.
  const raised = useMemo(
    () =>
      areas.flatMap(({ color, geometry }) => {
        const lifted = liftOntoTerraces(
          geometry,
          terrain.terraces,
          layers.lift,
        );
        return lifted ? [{ color, geometry: lifted, lift: 0 }] : [];
      }),
    [areas, terrain],
  );
  useEffect(() => () => raised.forEach((a) => a.geometry.dispose()), [raised]);

  return (
    <>
      {[
        ...areas.map((a) => ({ ...a, lift: layers.lift, key: a.color })),
        ...raised.map((a) => ({ ...a, key: `raised-${a.color}` })),
      ].map(({ key, color, geometry, lift }) => (
        <mesh
          key={key}
          geometry={geometry}
          position-y={lift}
          renderOrder={layers.greenery}
          receiveShadow
        >
          <meshStandardMaterial color={color} roughness={1} {...OVERLAY} />
        </mesh>
      ))}
      <Trees trees={data.trees} terrain={terrain} />
    </>
  );
}

function Trees({
  trees,
  terrain,
}: {
  trees: [number, number][];
  terrain: Terrain;
}) {
  const canopy = useRef<InstancedMesh>(null);
  const trunk = useRef<InstancedMesh>(null);

  useEffect(() => {
    if (!canopy.current || !trunk.current) return;
    const dummy = new Object3D();
    const tint = new Color();
    trees.forEach(([east, north], i) => {
      const size = 0.8 + hash(i) * 0.5;
      const [x, ground, z] = enuToWorld(
        east,
        north,
        terrain.heightAt(east, north),
      );
      dummy.position.set(x, ground + 6.5 * size, z);
      dummy.scale.setScalar(size);
      dummy.rotation.set(0, hash(i + 7) * Math.PI, 0);
      dummy.updateMatrix();
      canopy.current!.setMatrixAt(i, dummy.matrix);
      canopy.current!.setColorAt(
        i,
        tint.set(CANOPY).offsetHSL(0, 0, (hash(i + 3) - 0.5) * 0.08),
      );
      dummy.position.set(x, ground + 2.2 * size, z);
      dummy.updateMatrix();
      trunk.current!.setMatrixAt(i, dummy.matrix);
    });
    canopy.current.instanceMatrix.needsUpdate = true;
    if (canopy.current.instanceColor)
      canopy.current.instanceColor.needsUpdate = true;
    trunk.current.instanceMatrix.needsUpdate = true;
    // Bounds from the instances, so frustum culling sees raised trees.
    canopy.current.computeBoundingSphere();
    trunk.current.computeBoundingSphere();
  }, [trees, terrain]);

  if (trees.length === 0) return null;
  return (
    <>
      <instancedMesh
        ref={canopy}
        args={[undefined, undefined, trees.length]}
        castShadow
        receiveShadow
      >
        <icosahedronGeometry args={[4, 1]} />
        <meshStandardMaterial roughness={0.9} flatShading />
      </instancedMesh>
      <instancedMesh
        ref={trunk}
        args={[undefined, undefined, trees.length]}
        castShadow
      >
        <cylinderGeometry args={[0.35, 0.5, 4.4, 6]} />
        <meshStandardMaterial color={TRUNK} roughness={1} />
      </instancedMesh>
    </>
  );
}
