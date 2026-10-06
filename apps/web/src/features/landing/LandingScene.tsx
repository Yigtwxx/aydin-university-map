'use client';

import { Canvas, useFrame } from '@react-three/fiber';
import {
  Bloom,
  BrightnessContrast,
  EffectComposer,
  HueSaturation,
  Noise,
  Vignette,
} from '@react-three/postprocessing';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AdditiveBlending,
  BackSide,
  BufferGeometry,
  Color,
  DoubleSide,
  Float32BufferAttribute,
  type FogExp2,
  type Group,
  type Mesh,
  type MeshStandardMaterial,
  MultiplyBlending,
  NormalBlending,
  type PerspectiveCamera,
  type ShaderMaterial,
  type Texture,
  Vector2,
  Vector3,
} from 'three';

import { enuToWorld } from '@/features/campus/coords';
import { facadeUniforms, patchFacade } from '@/features/campus/facadeMaterial';
import { GroundLayer } from '@/features/campus/GroundLayer';
import { buildMassing } from '@/features/campus/massing';
import type { Building, Ground } from '@/features/campus/types';
import type { Sky } from '@/features/environment/hooks';

import { poseAt } from './cameraPath';
import type { Earth } from './earth';
import { type Credit, GoogleTiles } from './GoogleTiles';
import { landingState } from './state';
import { bakeCloudTexture, CLOUD_GLSL } from './cloudTexture';
import {
  bindLevels,
  createTerrainUniforms,
  terrainShaders,
} from './terrainMaterial';

const CLOUD_LAYERS = [2700, 3050];

/** Rings of vertices around the centre, denser inside: detail where we look. */
function polarGrid(r0: number, rMax: number, rings: number, segments: number) {
  const positions: number[] = [0, 0, 0];
  const indices: number[] = [];
  const k = Math.pow(rMax / r0, 1 / (rings - 1));
  for (let i = 0; i < rings; i++) {
    const r = r0 * Math.pow(k, i);
    for (let j = 0; j < segments; j++) {
      const a = (j / segments) * Math.PI * 2;
      positions.push(Math.cos(a) * r, 0, Math.sin(a) * r);
    }
  }
  const at = (i: number, j: number) => 1 + i * segments + (j % segments);
  for (let j = 0; j < segments; j++) indices.push(0, at(0, j + 1), at(0, j));
  for (let i = 0; i < rings - 1; i++)
    for (let j = 0; j < segments; j++) {
      const a = at(i, j);
      const b = at(i, j + 1);
      const c = at(i + 1, j);
      const d = at(i + 1, j + 1);
      indices.push(a, b, c, b, d, c);
    }
  const g = new BufferGeometry();
  g.setAttribute('position', new Float32BufferAttribute(positions, 3));
  g.setIndex(indices);
  return g;
}

interface Palette {
  top: string;
  horizon: string;
  /** Aerial haze seen looking down. */
  haze: string;
  sun: string;
}

const SKY: Record<Sky['phase'], Palette> = {
  day: { top: '#2F67B0', horizon: '#C3D6E8', haze: '#A9C2DC', sun: '#FFF1DC' },
  golden: {
    top: '#36589A',
    horizon: '#F0C29C',
    haze: '#9DB0CB',
    sun: '#FFC58C',
  },
  twilight: {
    top: '#18244A',
    horizon: '#6B678C',
    haze: '#3A4566',
    sun: '#9DB2E0',
  },
  night: {
    top: '#040915',
    horizon: '#16213A',
    haze: '#0D1528',
    sun: '#A9BEEA',
  },
};

function smooth(e0: number, e1: number, x: number) {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
}

type TerrainMode = 'full' | 'lights' | 'water';

function Terrain({
  earth,
  sky,
  cloudTex,
  mode = 'full',
}: {
  earth: Earth;
  sky: Sky;
  cloudTex?: Texture;
  /**
   * full: the satellite globe; lights: only the city lights, added over the
   * photoreal tiles at night; water: only the sea, over the photoreal tiles.
   */
  mode?: TerrainMode;
}) {
  const lightsOnly = mode === 'lights';
  const waterOnly = mode === 'water';
  const uniforms = useMemo(() => {
    const u = createTerrainUniforms();
    u.uLightsOnly!.value = lightsOnly ? 1 : 0;
    u.uWaterOnly!.value = waterOnly ? 1 : 0;
    if (waterOnly) {
      // Google's sea sits at true sea level: no relief exaggeration here,
      // and a couple of metres up so it wins against their water surface.
      u.uHeightScale!.value = 1;
      u.uLift!.value = 2;
    }
    return u;
  }, [lightsOnly, waterOnly]);
  const geometry = useMemo(() => polarGrid(5, 240000, 250, 384), []);
  const material = useRef<ShaderMaterial>(null);
  useEffect(() => {
    if (material.current)
      bindLevels(material.current, earth.levels, earth.originHeight);
  }, [earth]);
  useEffect(() => {
    const m = material.current;
    if (m && cloudTex) m.uniforms.uCloudTex!.value = cloudTex;
  }, [cloudTex]);
  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame(({ camera, clock }) => {
    const m = material.current;
    if (!m) return;
    const u = m.uniforms;
    const pose = landingState.pose;
    // Centre the grid between the ground under the camera and the target.
    const [ex, , ez] = enuToWorld(pose.eye[0], pose.eye[1]);
    const [tx, , tz] = enuToWorld(pose.target[0], pose.target[1]);
    const cx = Math.round((ex + tx) / 2 / 8) * 8;
    const cz = Math.round((ez + tz) / 2 / 8) * 8;
    (u.uCentre!.value as Vector2).set(cx, cz);
    u.uTime!.value = clock.elapsedTime;
    const altitude = camera.position.y;
    u.uHazeDensity!.value = hazeDensity(altitude);
    // The ground turns into the map only at the very end of the dive.
    u.uMapBlend!.value = 1 - smooth(1180, 1700, altitude);
  });

  useEffect(() => {
    const m = material.current;
    if (!m) return;
    const u = m.uniforms;
    const palette = SKY[sky.phase];
    const [x, y, z] = enuToWorld(...sky.sun.direction);
    (u.uSunDir!.value as Vector3).set(x, Math.max(y, -0.2), z).normalize();
    (u.uSunColor!.value as Color).set(palette.sun);
    (u.uSkyTop!.value as Color).set(palette.top);
    (u.uSkyHorizon!.value as Color).set(palette.horizon);
    // Seen from above, the air is the high sky's colour, not the horizon's.
    (u.uHazeColor!.value as Color).set(palette.haze);
    // City lights come on through dusk and are full once it is dark.
    u.uNightMix!.value = 1 - smooth(-0.14, -0.02, sky.sun.altitude);
  }, [sky]);

  return (
    <mesh
      geometry={geometry}
      frustumCulled={false}
      renderOrder={lightsOnly ? 6 : waterOnly ? 2 : 0}
    >
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={terrainShaders.vertexShader}
        fragmentShader={terrainShaders.fragmentShader}
        transparent={lightsOnly || waterOnly}
        blending={lightsOnly ? AdditiveBlending : NormalBlending}
        depthTest={!lightsOnly}
        depthWrite={mode === 'full'}
        polygonOffset={waterOnly}
        polygonOffsetFactor={-2}
        polygonOffsetUnits={-2}
      />
    </mesh>
  );
}

/** Aerial haze per metre: thick near the ground, thin from high up. */
function hazeDensity(altitude: number): number {
  const logAlt = Math.log(Math.max(altitude, 100));
  return (
    0.00008 +
    (0.0000055 - 0.00008) * smooth(Math.log(800), Math.log(30000), logAlt)
  );
}

const cloudVertex = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const cloudFragment = /* glsl */ `
  uniform float uTime;
  uniform float uScale;
  uniform vec2 uWind;
  uniform float uCoverage;
  uniform float uLayer;
  uniform vec3 uSunDir;
  uniform vec3 uLit;
  uniform vec3 uShade;
  uniform vec3 uHaze;
  uniform float uHazeDensity;
  varying vec3 vWorld;
  ${CLOUD_GLSL}
  void main() {
    // Each slab of the deck keeps the denser cores of the one below.
    float cover = cloudCover(vWorld.xz, uScale, uWind, uTime, uCoverage - uLayer * 0.08);
    if (cover < 0.01) discard;
    float lit = cloudCover(vWorld.xz + uSunDir.xz * 900.0, uScale, uWind, uTime, uCoverage);
    vec3 colour = mix(uLit, uShade, lit * 0.55 + uLayer * 0.08);
    float dist = length(cameraPosition - vWorld);
    float haze = 1.0 - exp(-dist * uHazeDensity * 0.7);
    colour = mix(colour, uHaze, haze);
    // Fade the deck out towards its edge so the plane never shows.
    float edge = 1.0 - smoothstep(45000.0, 75000.0, length(vWorld.xz - cameraPosition.xz));
    // Below the deck on the final approach the clouds give way to the map.
    float low = smoothstep(1500.0, 2400.0, cameraPosition.y);
    gl_FragColor = vec4(colour, pow(cover, 0.6) * 0.95 * edge * low);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

function cloudUniforms(layer: number) {
  return {
    uTime: { value: 0 },
    uScale: { value: 5200 },
    uWind: { value: new Vector2(0.0018, 0.0007) },
    uCoverage: { value: 0.38 },
    uLayer: { value: layer },
    uSunDir: { value: new Vector3(0.4, 0.6, -0.3) },
    uLit: { value: new Color('#ffffff') },
    uShade: { value: new Color('#9aa6b5') },
    uHaze: { value: new Color('#c3d6e8') },
    uHazeDensity: { value: 0.00002 },
    uCloudTex: { value: null as Texture | null },
  };
}

function CloudLayer({
  layer,
  height,
  sky,
  coverage,
  cloudTex,
}: {
  layer: number;
  height: number;
  sky: Sky;
  coverage: number;
  cloudTex: Texture;
}) {
  const uniforms = useMemo(() => cloudUniforms(layer), [layer]);
  const material = useRef<ShaderMaterial>(null);
  const mesh = useRef<Mesh>(null);
  useEffect(() => {
    const m = material.current;
    if (!m) return;
    const u = m.uniforms;
    const palette = SKY[sky.phase];
    const night = sky.phase === 'night' || sky.phase === 'twilight';
    const [x, y, z] = enuToWorld(...sky.sun.direction);
    (u.uSunDir!.value as Vector3).set(x, Math.max(y, 0.05), z).normalize();
    // Cloud tops stay white, warmed only a little by a low sun.
    (u.uLit!.value as Color)
      .set('#ffffff')
      .lerp(new Color(night ? '#3a4560' : palette.sun), night ? 1 : 0.3);
    (u.uShade!.value as Color).set(night ? '#1a2133' : '#8f9cad');
    (u.uHaze!.value as Color).set(palette.haze);
    u.uCoverage!.value = coverage;
    u.uCloudTex!.value = cloudTex;
  }, [sky, coverage, cloudTex]);
  useFrame(({ camera, clock }) => {
    const m = material.current;
    if (m) {
      m.uniforms.uTime!.value = clock.elapsedTime;
      m.uniforms.uHazeDensity!.value = hazeDensity(camera.position.y);
    }
    mesh.current?.position.set(camera.position.x, height, camera.position.z);
  });
  return (
    <mesh
      ref={mesh}
      rotation-x={-Math.PI / 2}
      renderOrder={10 + layer}
      frustumCulled={false}
    >
      <planeGeometry args={[160000, 160000, 1, 1]} />
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={cloudVertex}
        fragmentShader={cloudFragment}
        transparent
        depthWrite={false}
        side={DoubleSide}
      />
    </mesh>
  );
}

function Clouds({
  sky,
  coverage,
  cloudTex,
}: {
  sky: Sky;
  coverage: number;
  cloudTex: Texture;
}) {
  return (
    <>
      {CLOUD_LAYERS.map((height, i) => (
        <CloudLayer
          key={height}
          layer={i}
          height={height}
          sky={sky}
          coverage={coverage}
          cloudTex={cloudTex}
        />
      ))}
    </>
  );
}

/** Bake the cloud field on the first frame (one GPU pass). */
function useCloudField(): Texture | undefined {
  const [texture, setTexture] = useState<Texture>();
  useFrame(({ gl }) => {
    if (!texture) setTexture(bakeCloudTexture(gl));
  });
  useEffect(() => () => texture?.dispose(), [texture]);
  return texture;
}

const skyVertex = /* glsl */ `
  varying vec3 vDir;
  void main() {
    vDir = normalize(position);
    vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    gl_Position = p.xyww;
  }`;

const skyFragment = /* glsl */ `
  uniform vec3 uTop;
  uniform vec3 uHorizon;
  uniform vec3 uSun;
  uniform vec3 uSunColor;
  uniform float uAltitude;
  varying vec3 vDir;
  void main() {
    vec3 d = normalize(vDir);
    // Higher up, the zenith deepens towards space.
    vec3 top = mix(uTop, uTop * 0.45, smoothstep(8000.0, 30000.0, uAltitude));
    vec3 colour = mix(uHorizon, top, smoothstep(-0.02, 0.5, d.y));
    float s = max(dot(d, normalize(uSun)), 0.0);
    colour += uSunColor * (pow(s, 900.0) * 18.0 + pow(s, 12.0) * 0.25);
    gl_FragColor = vec4(colour, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }`;

function SkyDome({ sky }: { sky: Sky }) {
  const uniforms = useMemo(
    () => ({
      uTop: { value: new Color() },
      uHorizon: { value: new Color() },
      uSun: { value: new Vector3() },
      uSunColor: { value: new Color() },
      uAltitude: { value: 0 },
    }),
    [],
  );
  const material = useRef<ShaderMaterial>(null);
  const mesh = useRef<Mesh>(null);
  useEffect(() => {
    const m = material.current;
    if (!m) return;
    const u = m.uniforms;
    const palette = SKY[sky.phase];
    const [x, y, z] = enuToWorld(...sky.sun.direction);
    (u.uTop!.value as Color).set(palette.top);
    (u.uHorizon!.value as Color).set(palette.horizon);
    (u.uSun!.value as Vector3).set(x, y, z);
    (u.uSunColor!.value as Color).set(palette.sun);
  }, [sky]);
  useFrame(({ camera }) => {
    mesh.current?.position.copy(camera.position);
    const m = material.current;
    if (m) m.uniforms.uAltitude!.value = camera.position.y;
  });
  return (
    <mesh ref={mesh} renderOrder={-1} frustumCulled={false}>
      <sphereGeometry args={[1000, 32, 16]} />
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={skyVertex}
        fragmentShader={skyFragment}
        side={BackSide}
        depthWrite={false}
      />
    </mesh>
  );
}

/** Campus massing that rises out of the ground on the final approach. */
function RisingCampus({
  buildings,
  ground,
  sky,
}: {
  buildings: Building[];
  ground?: Ground;
  sky: Sky;
}) {
  const geometry = useMemo(() => buildMassing(buildings), [buildings]);
  const mesh = useRef<Mesh>(null);
  const material = useRef<MeshStandardMaterial>(null);
  const night = sky.phase === 'night' || sky.phase === 'twilight';
  useEffect(() => () => geometry?.dispose(), [geometry]);
  useFrame(({ camera }) => {
    const rise = 1 - smooth(1250, 2300, camera.position.y);
    if (mesh.current) {
      mesh.current.visible = rise > 0.002;
      mesh.current.scale.y = Math.max(rise, 0.001);
    }
    const uniforms = material.current && facadeUniforms(material.current);
    if (uniforms) uniforms.uNight.value = night ? 1 : 0;
  });
  const sun = useMemo(() => {
    const [x, y, z] = enuToWorld(...sky.sun.direction);
    return new Vector3(x, Math.max(y, 0.2), z).multiplyScalar(2000);
  }, [sky]);
  if (!geometry) return null;
  return (
    <>
      <hemisphereLight args={['#EAF2F7', '#B9AF99', night ? 0.35 : 0.7]} />
      <directionalLight position={sun} intensity={night ? 0.5 : 2.6} />
      {ground && <LandingGround data={ground} />}
      <mesh ref={mesh} geometry={geometry} visible={false}>
        <meshStandardMaterial
          ref={material}
          vertexColors
          roughness={0.86}
          onBeforeCompile={patchFacade}
        />
      </mesh>
    </>
  );
}

/** The map's vector streets, only once we are low enough to read them. */
function LandingGround({ data }: { data: Ground }) {
  const visible = useRef(false);
  const group = useRef<Group>(null);
  useFrame(({ camera }) => {
    const show = camera.position.y < 2600;
    if (show !== visible.current && group.current) {
      visible.current = show;
      group.current.visible = show;
    }
  });
  return (
    <group ref={group} visible={false}>
      <GroundLayer data={data} />
    </group>
  );
}

const CAMPUS_POINT = new Vector3(0, 20, 0);

function CameraRig({ reducedMotion }: { reducedMotion: boolean }) {
  const target = useRef(new Vector3());
  const projected = useRef(new Vector3());
  useFrame(({ camera, size }, delta) => {
    const state = landingState;
    const k = reducedMotion ? 1 : 1 - Math.exp(-delta * 5);
    state.progress += (state.target - state.progress) * k;
    const pose = poseAt(state.progress);
    state.pose = pose;
    const [x, y, z] = enuToWorld(...pose.eye);
    const cam = camera as PerspectiveCamera;
    cam.position.set(x, y, z);
    target.current.set(...enuToWorld(...pose.target));
    cam.lookAt(target.current);
    // Depth range follows the altitude: metres up close, 200 km up high.
    cam.near = Math.max(1, y * 0.0025);
    // Far enough for the horizon over the photoreal globe from 30 km up.
    cam.far = Math.max(80000, y * 40 + 200000);
    cam.fov = pose.fov;
    cam.updateProjectionMatrix();
    cam.updateMatrixWorld();
    state.altitude = y;
    const p = projected.current.copy(CAMPUS_POINT).project(cam);
    state.campus.x = (p.x * 0.5 + 0.5) * size.width;
    state.campus.y = (-p.y * 0.5 + 0.5) * size.height;
    state.campus.visible = p.z < 1 && Math.abs(p.x) < 1 && Math.abs(p.y) < 1;
  });
  return null;
}

/**
 * Night over the photoreal city: the daylight photo is multiplied down to a
 * blue-black, so the lights added on top read as a night view.
 */
function NightVeil({ sky }: { sky: Sky }) {
  const uniforms = useMemo(
    () => ({ uTint: { value: new Color('#ffffff') } }),
    [],
  );
  const material = useRef<ShaderMaterial>(null);
  useEffect(() => {
    const m = material.current;
    if (!m) return;
    // Dusk first cools and dims the photo; only real night turns it navy.
    const dark = 1 - smooth(-0.16, 0.03, sky.sun.altitude);
    const tint = new Color('#ffffff').lerp(
      new Color('#8d92b2'),
      smooth(0, 0.5, dark),
    );
    (m.uniforms.uTint!.value as Color)
      .copy(tint)
      .lerp(new Color('#1d2438'), smooth(0.5, 1, dark));
  }, [sky]);
  return (
    <mesh renderOrder={5} frustumCulled={false}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={
          'void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }'
        }
        fragmentShader={
          'uniform vec3 uTint; void main() { gl_FragColor = vec4(uTint, 1.0); }'
        }
        transparent
        premultipliedAlpha
        blending={MultiplyBlending}
        depthTest={false}
        depthWrite={false}
      />
    </mesh>
  );
}

/** Distance haze for the photoreal tiles (their materials take scene fog). */
function AerialFog({ sky }: { sky: Sky }) {
  const fog = useRef<FogExp2>(null);
  useFrame(({ camera }) => {
    if (fog.current) fog.current.density = hazeDensity(camera.position.y) * 0.9;
  });
  return (
    <fogExp2 ref={fog} attach="fog" args={[SKY[sky.phase].haze, 0.00002]} />
  );
}

type TilesState = 'loading' | 'ready' | 'failed';

interface SceneProps {
  earth?: Earth;
  sky: Sky;
  buildings?: Building[];
  ground?: Ground;
  reducedMotion: boolean;
  /** Share of the sky covered by the cloud deck, 0..1 (from live weather). */
  cloudCoverage?: number;
  /** Cesium ion token: stream Google's photorealistic city instead. */
  photorealToken?: string;
  onCredits?: (credits: Credit[] | undefined) => void;
  /** The first frame worth showing is on screen (photoreal or fallback). */
  onFirstView?: () => void;
}

/**
 * The film look: a touch of bloom for sun glints and city lights, a mild
 * warm grade, fine grain and a vignette. One composer pass, kept light.
 */
function FilmGrade({ night }: { night: boolean }) {
  return (
    <EffectComposer multisampling={0} enableNormalPass={false}>
      <Bloom
        mipmapBlur
        intensity={night ? 0.7 : 0.35}
        luminanceThreshold={night ? 0.32 : 0.82}
        luminanceSmoothing={0.2}
      />
      <HueSaturation saturation={night ? 0.04 : 0.1} />
      <BrightnessContrast brightness={0} contrast={0.08} />
      <Noise premultiply opacity={0.06} />
      <Vignette offset={0.28} darkness={0.5} />
    </EffectComposer>
  );
}

function LandingContents({
  earth,
  sky,
  buildings,
  ground,
  reducedMotion,
  cloudCoverage = 0.24,
  photorealToken,
  onCredits,
  onFirstView,
}: SceneProps) {
  const [tiles, setTiles] = useState<TilesState>('loading');
  const cloudTex = useCloudField();
  const photoreal = Boolean(photorealToken) && tiles !== 'failed';
  // The satellite scene shows until the photoreal city has its first view.
  const satellite = !photoreal || tiles !== 'ready';
  // Below the horizon the photoreal daylight photo needs the night grade.
  const night = sky.sun.altitude < 0.03;
  const errorTarget = useMemo(
    () => (typeof window !== 'undefined' && window.innerWidth < 768 ? 18 : 12),
    [],
  );
  return (
    <>
      <CameraRig reducedMotion={reducedMotion} />
      <SkyDome sky={sky} />
      {photoreal && photorealToken && (
        <>
          <AerialFog sky={sky} />
          <GoogleTiles
            prefetch
            token={photorealToken}
            errorTarget={errorTarget}
            onReady={() => {
              setTiles('ready');
              onFirstView?.();
            }}
            onFailure={() => {
              setTiles('failed');
              onCredits?.(undefined);
              onFirstView?.();
            }}
            onAttributions={(credits) => onCredits?.(credits)}
          />
        </>
      )}
      {satellite && earth && (
        <Terrain earth={earth} sky={sky} cloudTex={cloudTex} />
      )}
      {photoreal && tiles === 'ready' && earth && (
        <Terrain earth={earth} sky={sky} cloudTex={cloudTex} mode="water" />
      )}
      {photoreal && tiles === 'ready' && night && (
        <>
          <NightVeil sky={sky} />
          {earth && <Terrain earth={earth} sky={sky} mode="lights" />}
        </>
      )}
      {!reducedMotion && cloudTex && (
        <Clouds sky={sky} coverage={cloudCoverage} cloudTex={cloudTex} />
      )}
      {!photoreal && buildings && (
        <RisingCampus buildings={buildings} ground={ground} sky={sky} />
      )}
      {!reducedMotion && <FilmGrade night={night} />}
    </>
  );
}

export function LandingScene(props: SceneProps) {
  const first = poseAt(0);
  return (
    <Canvas
      // Film quality comes from the grade, not raw pixels: 1.5x is plenty
      // and keeps laptops cool.
      dpr={[1, 1.5]}
      frameloop={props.reducedMotion ? 'demand' : 'always'}
      camera={{
        fov: first.fov,
        near: 50,
        far: 200000,
        position: enuToWorld(...first.eye),
      }}
      gl={{ antialias: true, powerPreference: 'high-performance' }}
      onCreated={({ scene }) => {
        scene.background = new Color(SKY[props.sky.phase].horizon);
      }}
    >
      <LandingContents {...props} />
    </Canvas>
  );
}
