'use client';

import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  type BufferGeometry,
  Color,
  InstancedMesh,
  Matrix4,
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
import { useFurniture } from './queries';
import { type Terrain, terrainOf } from './terrain';

/**
 * Camera distances (m) over which each class of object dissolves away, so
 * the overview never shimmers with sub-pixel chairs. Stairs and terraces
 * are part of the ground and always stay.
 */
const FADE = {
  /** Chairs, tables, bins, bollards, bike racks. */
  small: [150, 240],
  /** Benches, planters, umbrellas, railings. */
  medium: [280, 430],
  /** Lamp posts. */
  tall: [480, 720],
  /** Light pools under the lamps at night. */
  pools: [650, 950],
} as const satisfies Record<string, readonly [number, number]>;

const FADE_OF: Record<InstanceKind, 'small' | 'medium' | 'tall'> = {
  chair: 'small',
  table: 'small',
  bin: 'small',
  bollard: 'small',
  hoop: 'small',
  bench: 'medium',
  planter: 'medium',
  umbrella: 'medium',
  lamp: 'tall',
  lens: 'tall',
  booth: 'medium',
  kiosk: 'medium',
  emblem: 'medium',
  letters: 'medium',
  topiary: 'small',
  statue: 'medium',
  globe: 'tall',
  stand: 'small',
  hedge: 'medium',
  sign: 'medium',
  flagpole: 'tall',
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

/**
 * Dissolves fragments between `near` and `far` metres from the camera with a
 * screen-space dither (no transparency, so no sorting) and drops them past it.
 */
function dissolveWithDistance(
  material: MeshStandardMaterial,
  [near, far]: readonly [number, number],
): MeshStandardMaterial {
  const fade = { value: new Vector2(near, far) };
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uFade = fade;
    shader.vertexShader = `varying float vFadeDistance;\n${shader.vertexShader.replace(
      '#include <project_vertex>',
      '#include <project_vertex>\n\tvFadeDistance = length(mvPosition.xyz);',
    )}`;
    shader.fragmentShader = `uniform vec2 uFade;\nvarying float vFadeDistance;\n${shader.fragmentShader.replace(
      '#include <clipping_planes_fragment>',
      /* glsl */ `#include <clipping_planes_fragment>
	float fadeK = smoothstep(uFade.x, uFade.y, vFadeDistance);
	float fadeNoise = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
	if (fadeK >= 1.0 || fadeK > fadeNoise) discard;`,
    )}`;
  };
  material.customProgramCacheKey = () => 'furniture-dissolve';
  return material;
}

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

  const materials = useMemo(() => {
    const make = (fade: keyof typeof FADE) =>
      dissolveWithDistance(
        new MeshStandardMaterial({
          vertexColors: true,
          roughness: 0.72,
          metalness: 0.05,
        }),
        FADE[fade],
      );
    return {
      small: make('small'),
      medium: make('medium'),
      tall: make('tall'),
      metal: dissolveWithDistance(
        new MeshStandardMaterial({
          color: furnitureColors.metal,
          roughness: 0.45,
          metalness: 0.55,
        }),
        FADE.medium,
      ),
      lens: dissolveWithDistance(
        new MeshStandardMaterial({
          vertexColors: true,
          roughness: 0.35,
          emissive: new Color(LENS_GLOW),
          emissiveIntensity: 0,
        }),
        FADE.tall,
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
  }, []);
  useEffect(
    () => () => {
      for (const material of Object.values(materials)) material.dispose();
    },
    [materials],
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
  useFrame((_, delta) => {
    const target = night ? 1 : 0;
    const k = reducedMotion ? 1 : 1 - Math.exp(-delta * 1.5);
    glow.current += (target - glow.current) * k;
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
        <mesh geometry={masonry} castShadow receiveShadow>
          <meshStandardMaterial vertexColors roughness={0.9} metalness={0} />
        </mesh>
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
              : materials[FADE_OF[kind]]
          }
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
  castShadow,
}: {
  kind: InstanceKind;
  matrices: Matrix4[];
  material: MeshStandardMaterial;
  castShadow: boolean;
}) {
  const geometry = useMemo<BufferGeometry>(() => itemGeometry(kind), [kind]);
  const mesh = useMemo(() => {
    const instanced = new InstancedMesh(geometry, material, matrices.length);
    matrices.forEach((m, i) => instanced.setMatrixAt(i, m));
    instanced.instanceMatrix.needsUpdate = true;
    instanced.computeBoundingSphere();
    instanced.castShadow = castShadow;
    instanced.receiveShadow = true;
    return instanced;
  }, [geometry, material, matrices, castShadow]);
  useEffect(() => () => mesh.dispose(), [mesh]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <primitive object={mesh} />;
}
