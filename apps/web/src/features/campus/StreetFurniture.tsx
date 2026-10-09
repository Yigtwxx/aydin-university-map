'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  type BufferGeometry,
  Color,
  InstancedMesh,
  Matrix4,
  type MeshDepthMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  ShaderMaterial,
  Vector2,
  Vector3,
} from 'three';

import { layers } from './constants';
import type { Furniture } from './furniture';
import {
  furnitureColors,
  furnitureInstances,
  type InstanceKind,
  itemGeometry,
  fenceGeometry,
  masonryGeometry,
  railingGeometry,
} from './furnitureGeometry';
import {
  cartographic,
  cartographicDepth,
  FADE,
  type FurnitureClass,
  makeViewer,
} from './furnitureScale';
import { patchPaving } from './paving';
import { useFurniture } from './queries';
import { type Terrain, terrainOf } from './terrain';

/** How each kind grows and fades with distance (see furnitureScale). */
const CLASS_OF: Record<InstanceKind, FurnitureClass> = {
  chair: 'small',
  table: 'small',
  bin: 'small',
  bollard: 'small',
  hoop: 'small',
  bench: 'medium',
  planter: 'medium',
  umbrella: 'large',
  lamp: 'large',
  lens: 'large',
  booth: 'large',
  kiosk: 'large',
  emblem: 'large',
  letters: 'large',
  topiary: 'small',
  statue: 'large',
  globe: 'large',
  stand: 'small',
  hedge: 'medium',
  sign: 'medium',
  flagpole: 'large',
};

/**
 * Objects big enough to cast a readable shadow at the sun's shadow-map
 * resolution (~0.4 m a texel); the rest are grounded by ambient occlusion.
 */
const CASTS_SHADOW = new Set<InstanceKind>([
  'bench',
  'planter',
  'umbrella',
  'booth',
  'kiosk',
  'emblem',
  'letters',
  'statue',
  'hedge',
]);

const POOL_RADIUS_M = 6.5;
const POOL_COLOR = '#FFB86A';
const LENS_GLOW = '#FFCF8A';

const poolVertex = /* glsl */ `
  varying vec2 vUv;
  varying float vDistance;
  void main() {
    vUv = uv;
    vec4 mvPosition = modelViewMatrix * instanceMatrix * vec4(position, 1.0);
    vDistance = length(mvPosition.xyz);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

/** A warm pool of lamplight on the paving: soft falloff, added to the scene. */
const poolFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uIntensity;
  uniform vec2 uFade;
  varying vec2 vUv;
  varying float vDistance;
  void main() {
    float r = length(vUv - 0.5) * 2.0;
    float falloff = pow(max(0.0, 1.0 - r), 2.4);
    float fade = 1.0 - smoothstep(uFade.x, uFade.y, vDistance);
    gl_FragColor = vec4(uColor * uIntensity, falloff * fade);
    #include <colorspace_fragment>
  }
`;

/**
 * The campus at human scale: raised terraces with their walls, stairs with
 * treads and handrails, ramps, railings, benches, planters, bollards, bins,
 * lamps (lit at night), bike racks and café terraces. Drawn from
 * `furniture.json`; nothing when the asset is missing.
 */
export function StreetFurniture({
  night,
  reducedMotion,
}: {
  night: boolean;
  reducedMotion: boolean;
}) {
  const { data } = useFurniture();
  if (!data || isEmpty(data)) return null;
  return (
    <FurnitureScene
      furniture={data}
      terrain={terrainOf(data)}
      night={night}
      reducedMotion={reducedMotion}
    />
  );
}

function isEmpty(f: Furniture): boolean {
  return (
    f.terraces.length +
      f.stairs.length +
      f.ramps.length +
      f.railings.length +
      f.items.length +
      f.seating.length ===
    0
  );
}

function FurnitureScene({
  furniture,
  terrain,
  night,
  reducedMotion,
}: {
  furniture: Furniture;
  terrain: Terrain;
  night: boolean;
  reducedMotion: boolean;
}) {
  const masonry = useMemo(
    () => masonryGeometry(furniture, terrain),
    [furniture, terrain],
  );
  const rails = useMemo(
    () => railingGeometry(furniture, terrain),
    [furniture, terrain],
  );
  const fence = useMemo(() => fenceGeometry(furniture), [furniture]);
  const instances = useMemo(
    () => furnitureInstances(furniture, terrain),
    [furniture, terrain],
  );
  useEffect(
    () => () => {
      masonry?.dispose();
      rails?.dispose();
      fence?.dispose();
    },
    [masonry, rails, fence],
  );

  // Where the camera is, for the furniture that grows with distance.
  const viewer = useMemo(() => makeViewer(), []);
  useFrame(({ camera }) => viewer.value.copy(camera.position));

  const materials = useMemo(() => {
    const make = (cls: FurnitureClass) =>
      cartographic(
        new MeshStandardMaterial({
          vertexColors: true,
          roughness: 0.72,
          metalness: 0.05,
        }),
        viewer,
        cls,
      );
    const masonry = new MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.9,
      metalness: 0,
    });
    patchPaving(masonry);
    return {
      masonry,
      small: make('small'),
      medium: make('medium'),
      large: make('large'),
      metal: cartographic(
        new MeshStandardMaterial({
          color: furnitureColors.metal,
          roughness: 0.45,
          metalness: 0.55,
        }),
        viewer,
        'medium',
        FADE.rails,
      ),
      lens: cartographic(
        new MeshStandardMaterial({
          vertexColors: true,
          roughness: 0.35,
          emissive: new Color(LENS_GLOW),
          emissiveIntensity: 0,
        }),
        viewer,
        'large',
      ),
      pool: new ShaderMaterial({
        vertexShader: poolVertex,
        fragmentShader: poolFragment,
        uniforms: {
          uColor: { value: new Color(POOL_COLOR) },
          uIntensity: { value: 0 },
          uFade: { value: new Vector2(...FADE.pools) },
        },
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        polygonOffset: true,
        polygonOffsetFactor: -3,
        polygonOffsetUnits: -3,
      }),
    };
  }, [viewer]);
  // Shadows of the furniture that casts them, grown with it.
  const depths = useMemo(
    () => ({
      small: cartographicDepth(viewer, 'small'),
      medium: cartographicDepth(viewer, 'medium'),
      large: cartographicDepth(viewer, 'large'),
    }),
    [viewer],
  );
  useEffect(
    () => () => {
      for (const material of Object.values(materials)) material.dispose();
      for (const material of Object.values(depths)) material.dispose();
    },
    [materials, depths],
  );

  // Lamps glow and pool light on the paving over dusk, instead of switching.
  const glow = useRef(night ? 1 : 0);
  const pools = useRef<InstancedMesh>(null);
  const lit = useRef<{ lens: MeshStandardMaterial; pool: ShaderMaterial }>(
    undefined,
  );
  useEffect(() => {
    lit.current = { lens: materials.lens, pool: materials.pool };
  }, [materials]);
  // On demand: dusk or dawn asks for frames until the lamps settle.
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => invalidate(), [night, invalidate]);
  useFrame((_, delta) => {
    const target = night ? 1 : 0;
    const k = reducedMotion ? 1 : 1 - Math.exp(-delta * 1.5);
    glow.current += (target - glow.current) * k;
    if (Math.abs(target - glow.current) > 0.002) invalidate();
    else glow.current = target;
    const g = glow.current;
    if (lit.current) {
      lit.current.lens.emissiveIntensity = 2.6 * g;
      lit.current.pool.uniforms.uIntensity!.value = 0.5 * g;
    }
    if (pools.current) pools.current.visible = g > 0.01;
  });

  const lamps = instances.get('lamp');
  const poolMesh = useMemo(() => {
    if (!lamps?.length) return undefined;
    const plane = new PlaneGeometry(1, 1);
    plane.rotateX(-Math.PI / 2);
    const mesh = new InstancedMesh(plane, materials.pool, lamps.length);
    const position = new Vector3();
    const pool = new Matrix4();
    lamps.forEach((m, i) => {
      position.setFromMatrixPosition(m);
      pool
        .makeScale(POOL_RADIUS_M * 2, 1, POOL_RADIUS_M * 2)
        .setPosition(position.x, position.y + 0.08, position.z);
      mesh.setMatrixAt(i, pool);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
    mesh.renderOrder = layers.outline - 0.5;
    mesh.visible = false;
    return mesh;
  }, [lamps, materials]);
  useEffect(
    () => () => {
      poolMesh?.geometry.dispose();
      poolMesh?.dispose();
    },
    [poolMesh],
  );

  return (
    <group>
      {masonry && (
        <mesh
          geometry={masonry}
          material={materials.masonry}
          castShadow
          receiveShadow
        />
      )}
      {rails && <mesh geometry={rails} material={materials.metal} />}
      {fence && (
        <mesh
          geometry={fence}
          material={materials.medium}
          castShadow
          receiveShadow
        />
      )}
      {[...instances].map(([kind, matrices]) => (
        <Instances
          key={kind}
          kind={kind}
          matrices={matrices}
          material={
            kind === 'lens' || kind === 'globe'
              ? materials.lens
              : materials[CLASS_OF[kind]]
          }
          depthMaterial={depths[CLASS_OF[kind]]}
          castShadow={CASTS_SHADOW.has(kind)}
        />
      ))}
      {poolMesh && <primitive ref={pools} object={poolMesh} />}
    </group>
  );
}

/** One model drawn many times: one draw call per kind. */
function Instances({
  kind,
  matrices,
  material,
  depthMaterial,
  castShadow,
}: {
  kind: InstanceKind;
  matrices: Matrix4[];
  material: MeshStandardMaterial;
  depthMaterial: MeshDepthMaterial;
  castShadow: boolean;
}) {
  const geometry = useMemo<BufferGeometry>(() => itemGeometry(kind), [kind]);
  const mesh = useMemo(() => {
    const instanced = new InstancedMesh(geometry, material, matrices.length);
    matrices.forEach((m, i) => instanced.setMatrixAt(i, m));
    instanced.instanceMatrix.needsUpdate = true;
    instanced.computeBoundingSphere();
    instanced.castShadow = castShadow;
    instanced.customDepthMaterial = depthMaterial;
    instanced.receiveShadow = true;
    return instanced;
  }, [geometry, material, depthMaterial, matrices, castShadow]);
  useEffect(() => () => mesh.dispose(), [mesh]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <primitive object={mesh} />;
}
