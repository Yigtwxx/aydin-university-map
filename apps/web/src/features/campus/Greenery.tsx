'use client';

import { useEffect, useMemo, useRef } from 'react';
import {
  CanvasTexture,
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
import { raisedAreaGeometry, type RaisedStyle } from './raisedAreas';
import type { Terrain } from './terrain';
import { positionHash, type TreeRecord, treeShape } from './treeShape';
import type { Greenery as GreeneryData } from './types';
import { crownGeometry, woodTrees } from './woodland';

const AREA_COLORS: Record<string, string> = {
  pitch: '#6FA85A',
  park: '#8DB36B',
  garden: '#8DB36B',
};
const GRASS = '#9DBE78';
/** Campus lawns: a little greener, in kerbs painted traffic yellow. */
const LAWN = '#8CBF68';
const KERB = '#E9B92E';
/** Height of a lawn's kerb above the paving, metres. */
export const KERB_M = 0.15;
/** Flower beds: a planting mound standing a little proud of the lawn. */
const BLOOMS = '#F2B92B';
const FOLIAGE = '#5E8A3E';
const BED_M = 0.32;
/** Ornamental pools: a basin whose white coping stands a little proud. */
const WATER = '#4FA6C9';
const COPING = '#ECE8DE';
const POOL_M = 0.35;
/** Traced areas drawn as raised slabs: top colour, side colour, height. */
const RAISED: Record<string, RaisedStyle> = {
  lawn: { top: LAWN, side: KERB, depth: KERB_M },
  flowerbed: { top: BLOOMS, side: FOLIAGE, depth: BED_M },
  pool: { top: WATER, side: COPING, depth: POOL_M },
};
const TRUNK = '#6E5A44';

export function Greenery({ data }: { data: GreeneryData }) {
  const terrain = useTerrain();
  const woods = useMemo(
    () =>
      woodTrees(
        data.areas.filter((a) => a.kind === 'forest').map((a) => a.outline),
      ),
    [data],
  );
  const areas = useMemo(() => {
    const byColor = new Map<string, ShapeGeometry[]>();
    for (const area of data.areas) {
      if (area.kind in RAISED) continue;
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
      {Object.entries(RAISED).map(([kind, style]) => (
        <RaisedAreas
          key={kind}
          data={data}
          terrain={terrain}
          kind={kind}
          style={style}
        />
      ))}
      <Trees trees={data.trees} woods={woods} terrain={terrain} />
    </>
  );
}

/**
 * Lawns, flower beds and pools traced on the panoramas: raised on the ground
 * they stand on, their sides the kerb (or foliage, or coping), their top the
 * grass (or blooms, or water).
 */
function RaisedAreas({
  data,
  terrain,
  kind,
  style,
}: {
  data: GreeneryData;
  terrain: Terrain;
  kind: string;
  style: RaisedStyle;
}) {
  const geometry = useMemo(
    () =>
      raisedAreaGeometry(
        data.areas.filter((a) => a.kind === kind).map((a) => a.outline),
        style,
        (e, n) => terrain.heightAt(e, n),
      ),
    [data, terrain, kind, style],
  );
  useEffect(() => () => geometry?.dispose(), [geometry]);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry} castShadow receiveShadow>
      <meshStandardMaterial vertexColors roughness={0.95} />
    </mesh>
  );
}

/** Crown greens, picked per tree: plane, a deeper broadleaf, a yellower one. */
const CANOPY_TONES = ['#5F8F4E', '#4E8046', '#73984F'] as const;

interface Stand {
  key: string;
  trees: TreeRecord[];
  /** Lobe subdivision: 1 near the campus, 0 for the far woods. */
  detail: number;
}

function Trees({
  trees,
  woods,
  terrain,
}: {
  trees: TreeRecord[];
  woods: TreeRecord[];
  terrain: Terrain;
}) {
  const stands: Stand[] = [
    { key: 'trees', trees, detail: 1 },
    { key: 'woods', trees: woods, detail: 0 },
  ];
  return (
    <>
      {stands.map(
        (stand) =>
          stand.trees.length > 0 && (
            <TreeStand key={stand.key} stand={stand} terrain={terrain} />
          ),
      )}
      <TreeShade trees={[...trees, ...woods]} terrain={terrain} />
    </>
  );
}

function TreeStand({ stand, terrain }: { stand: Stand; terrain: Terrain }) {
  const { trees, detail } = stand;
  const canopy = useRef<InstancedMesh>(null);
  const trunk = useRef<InstancedMesh>(null);
  const crown = useMemo(() => crownGeometry(detail), [detail]);
  useEffect(() => () => crown.dispose(), [crown]);

  // Lay the instances; again for a new crown, which rebuilds the mesh.
  useEffect(() => {
    if (!canopy.current || !trunk.current) return;
    const dummy = new Object3D();
    const tint = new Color();
    trees.forEach((tree, i) => {
      const [east, north] = tree;
      const shape = treeShape(tree);
      const [x, ground, z] = enuToWorld(
        east,
        north,
        terrain.heightAt(east, north),
      );
      // Unit crown (radius 1) and unit trunk (height 1, foot radius 1).
      dummy.position.set(x, ground + shape.crownY, z);
      dummy.scale.set(
        shape.crownRadius,
        shape.crownHalfHeight,
        shape.crownRadius,
      );
      dummy.rotation.set(0, shape.yaw, 0);
      dummy.updateMatrix();
      canopy.current!.setMatrixAt(i, dummy.matrix);
      const tone =
        CANOPY_TONES[
          Math.floor(positionHash(east, north, 5) * CANOPY_TONES.length)
        ]!;
      canopy.current!.setColorAt(
        i,
        tint.set(tone).offsetHSL(0, 0, shape.shade),
      );
      dummy.position.set(x, ground + shape.trunkHeight / 2, z);
      dummy.rotation.set(0, 0, 0);
      dummy.scale.set(shape.trunkRadius, shape.trunkHeight, shape.trunkRadius);
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
  }, [trees, terrain, crown]);

  return (
    <>
      <instancedMesh
        ref={canopy}
        args={[crown, undefined, trees.length]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial vertexColors roughness={0.85} />
      </instancedMesh>
      <instancedMesh
        ref={trunk}
        args={[undefined, undefined, trees.length]}
        castShadow
      >
        <cylinderGeometry args={[0.7, 1, 1, 6]} />
        <meshStandardMaterial color={TRUNK} roughness={1} />
      </instancedMesh>
    </>
  );
}

/**
 * A soft dark disc on the ground under every crown: the shade a tree keeps
 * around its foot whatever the sun does (overcast, night, outside the sun's
 * shadow map), so trees sit on the ground instead of floating.
 */
function TreeShade({
  trees,
  terrain,
}: {
  trees: TreeRecord[];
  terrain: Terrain;
}) {
  const mesh = useRef<InstancedMesh>(null);
  const texture = useMemo(() => shadeTexture(), []);
  useEffect(() => () => texture?.dispose(), [texture]);

  useEffect(() => {
    if (!mesh.current) return;
    const dummy = new Object3D();
    trees.forEach((tree, i) => {
      const [east, north] = tree;
      const shape = treeShape(tree);
      const [x, ground, z] = enuToWorld(
        east,
        north,
        terrain.heightAt(east, north),
      );
      // Above a lawn's top too, so trees planted in lawns keep their shade.
      dummy.position.set(x, ground + KERB_M + 0.03, z);
      dummy.rotation.set(-Math.PI / 2, 0, 0);
      const r = shape.crownRadius * 1.25;
      dummy.scale.set(r, r, 1);
      dummy.updateMatrix();
      mesh.current!.setMatrixAt(i, dummy.matrix);
    });
    mesh.current.instanceMatrix.needsUpdate = true;
    mesh.current.computeBoundingSphere();
  }, [trees, terrain]);

  if (!texture || trees.length === 0) return null;
  return (
    <instancedMesh
      ref={mesh}
      args={[undefined, undefined, trees.length]}
      renderOrder={layers.greenery + 0.5}
    >
      <planeGeometry args={[2, 2]} />
      <meshBasicMaterial
        color="#1E2A18"
        alphaMap={texture}
        transparent
        opacity={0.32}
        {...OVERLAY}
      />
    </instancedMesh>
  );
}

/** Radial falloff for the shade under a tree (white = dark), or none in tests. */
function shadeTexture(): CanvasTexture | undefined {
  if (typeof document === 'undefined') return undefined;
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return undefined;
  const g = ctx.createRadialGradient(
    size / 2,
    size / 2,
    0,
    size / 2,
    size / 2,
    size / 2,
  );
  g.addColorStop(0, '#FFFFFF');
  g.addColorStop(0.45, '#B0B0B0');
  g.addColorStop(1, '#000000');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new CanvasTexture(canvas);
}
