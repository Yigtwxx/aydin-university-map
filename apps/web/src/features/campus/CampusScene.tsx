'use client';

import { CameraControls, Environment } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { EffectComposer, N8AO, Vignette } from '@react-three/postprocessing';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  BackSide,
  Box3,
  Color,
  type MeshStandardMaterial,
  type PerspectiveCamera,
  Vector3,
} from 'three';
import { MeshBVH } from 'three-mesh-bvh';

import type { Sky } from '@/features/environment/hooks';
import { type Credit, GoogleTiles } from '@/features/landing/GoogleTiles';
import {
  type Condition,
  precipitationOf,
} from '@/features/environment/weather';
import {
  headingFromAzimuth,
  POLAR_TOP_DOWN,
  useCameraStore,
} from '@/features/map/cameraStore';

import { occluders } from './anchors';
import { OpeningClock } from './OpeningClock';
import { resetIntroClock } from './opening';
import { palette } from './constants';
import { enuToWorld } from './coords';
import { facadeUniforms, patchFacade } from './facadeMaterial';
import { Greenery } from './Greenery';
import { GroundLayer } from './GroundLayer';
import { IntroGradeEffect } from './openingGrade';
import { buildMassing } from './massing';
import { OverlayProjector } from './OverlayProjector';
import { Precipitation } from './Precipitation';
import { RouteRibbon } from './RouteRibbon';
import { SkyRig } from './SkyRig';
import type {
  Building,
  CampusGraph,
  GraphNode,
  Greenery as GreeneryData,
  Ground,
} from './types';

/** Where the camera starts before gliding in: high above the Marmara side. */
const INTRO_POSITION: [number, number, number] = [420, 1150, 1500];
const INTRO_SMOOTH_S = 1.5;
/** The opening's tilt from straight above down into the 3D view. */
const ASSEMBLE_SMOOTH_S = 1.1;
const SMOOTH_S = 0.6;

/** Screen area (CSS px) covered by panels; the view centres on the rest. */
export interface SceneInsets {
  left: number;
  bottom: number;
}

interface SceneProps {
  graph: CampusGraph;
  insets: SceneInsets;
  buildings: Building[];
  greenery?: GreeneryData;
  ground?: Ground;
  routeNodeIds?: string[];
  /**
   * The runs of the route to draw (node ids each); the line breaks between
   * them. Without it the whole route is one line.
   */
  routeParts?: string[][];
  /** Node of the route step being previewed in 360°. */
  activeNodeId?: string;
  /** Node shown in 360° while exploring without a route. */
  exploreNodeId?: string;
  sky: Sky;
  condition?: Condition;
  reducedMotion: boolean;
  /**
   * Google's photorealistic tiles instead of the drawn massing and ground
   * (Cesium ion token); the route, pins and labels stay on top.
   */
  photoreal?: { token: string; onCredits: (credits: Credit[]) => void };
  /** Render on demand only (the landing dive covers the map). */
  paused?: boolean;
  /** Keep the opening camera until the landing hands over. */
  holdIntro?: boolean;
  /**
   * Play the opening (opening.ts) from the dot map into the campus. Read at
   * mount; the callbacks fire when the chrome may come in and at the end.
   */
  assemble?: { onReveal: () => void; onDone: () => void };
}

export function CampusScene(props: SceneProps) {
  return (
    <Canvas
      shadows="percentage"
      dpr={[1, 2]}
      // Paused under the landing dive: one frame at mount compiles every
      // shader and uploads the massing, so taking over later costs nothing.
      frameloop={props.paused ? 'demand' : 'always'}
      camera={{ fov: 34, near: 2, far: 5200, position: INTRO_POSITION }}
      gl={{ antialias: false, powerPreference: 'high-performance' }}
    >
      <SceneContents {...props} />
    </Canvas>
  );
}

function SceneContents({
  graph,
  buildings,
  greenery,
  ground,
  routeNodeIds,
  routeParts,
  activeNodeId,
  exploreNodeId,
  sky,
  condition,
  insets,
  reducedMotion,
  photoreal,
  holdIntro = false,
  assemble,
}: SceneProps) {
  const controls = useRef<CameraControls>(null);
  const introduced = useRef(false);
  // The opening plays once, from mount: later prop changes do not restart it.
  const [assembling, setAssembling] = useState(() => Boolean(assemble));
  const [glided, setGlided] = useState(false);
  const onAssembleRef = useRef(assemble);
  useEffect(() => {
    if (assemble) onAssembleRef.current = assemble;
  }, [assemble]);
  const [playsOpening] = useState(() => Boolean(assemble));
  useLayoutEffect(() => resetIntroClock(playsOpening), [playsOpening]);
  const waiting = holdIntro || (assembling && !glided);
  // The free view's shape, read when framing (not a dependency: dragging the
  // sheet must not refit the camera).
  const size = useThree((s) => s.size);
  const fov = useThree((s) => (s.camera as PerspectiveCamera).fov);
  const view = useRef({ aspect: 1, fov: 34 });
  // Framing waits for the canvas to be measured, or it fits the wrong shape.
  const measured = size.width > 0 && size.height > 0;
  // The campus buildings stay in the overview, not only the walkable spots.
  const campusCorners = useMemo(
    () =>
      buildings
        .filter((b) => b.campus)
        .flatMap((b) => b.outline.map((p): [number, number] => [p[0], p[1]])),
    [buildings],
  );
  useLayoutEffect(() => {
    // Phones: the map controls' column covers the right edge.
    const controls = size.width < 768 ? 56 : 0;
    const width = Math.max(1, size.width - insets.left - controls);
    const height = Math.max(1, size.height - insets.bottom);
    view.current = { aspect: width / height, fov };
  }, [size, insets, fov]);
  // Selectors, not the whole store: the heading changes every frame while
  // the camera turns, and the scene must not re-render for it.
  const setControls = useCameraStore((s) => s.setControls);
  const setHeading = useCameraStore((s) => s.setHeading);
  const setTopDown = useCameraStore((s) => s.setTopDown);
  const fitRequest = useCameraStore((s) => s.fitRequest);

  const route = useMemo(
    () =>
      (routeNodeIds ?? [])
        .map((id) => graph.byId.get(id))
        .filter((n): n is GraphNode => !!n),
    [graph, routeNodeIds],
  );
  const hasRoute = route.length > 1;
  const ribbons = useMemo(
    () =>
      routeParts
        ? routeParts.map((part) =>
            part
              .map((id) => graph.byId.get(id))
              .filter((n): n is GraphNode => !!n),
          )
        : hasRoute
          ? [route]
          : [],
    [graph, routeParts, route, hasRoute],
  );
  const precipitation = condition ? precipitationOf(condition) : undefined;

  // Share the controls with the DOM map controls and report the heading.
  useEffect(() => {
    const ctl = controls.current;
    if (!ctl) return;
    setControls(ctl);
    const onUpdate = () => {
      setHeading(headingFromAzimuth(ctl.azimuthAngle));
      setTopDown(ctl.polarAngle < POLAR_TOP_DOWN + 0.15);
    };
    ctl.addEventListener('update', onUpdate);
    return () => {
      ctl.removeEventListener('update', onUpdate);
      setControls(undefined);
    };
  }, [setControls, setHeading, setTopDown]);

  // The opening starts high over the campus, looking almost straight down.
  useEffect(() => {
    const ctl = controls.current;
    // Before the tilt only: a later graph (a refetch) must not pull it back.
    if (!ctl || !playsOpening || glided || !measured) return;
    const pose = overview(
      graph.nodes,
      false,
      view.current.aspect,
      view.current.fov,
      campusCorners,
    );
    // High enough to see the neighbourhood rise, within maxDistance.
    const radius = Math.min(1380, Math.max(1200, pose.distance * 1.55));
    const azimuth = Math.atan2(OVERVIEW[0], OVERVIEW[2]) - 0.6;
    const polar = 0.2;
    void ctl.setLookAt(
      pose.centre.x + radius * Math.sin(polar) * Math.sin(azimuth),
      radius * Math.cos(polar),
      pose.centre.z + radius * Math.sin(polar) * Math.cos(azimuth),
      pose.centre.x,
      0,
      pose.centre.z,
      false,
    );
  }, [graph, playsOpening, glided, measured, campusCorners]);

  // Glide in on first load, then frame the route, the step being previewed
  // (from behind the walker, facing the next node) or the whole network.
  useEffect(() => {
    const ctl = controls.current;
    if (!ctl || waiting || !measured) return;
    const animate = !reducedMotion;
    if (!introduced.current) {
      introduced.current = true;
      if (animate) {
        ctl.smoothTime = playsOpening ? ASSEMBLE_SMOOTH_S : INTRO_SMOOTH_S;
        const restore = () => {
          ctl.smoothTime = SMOOTH_S;
          ctl.removeEventListener('rest', restore);
        };
        ctl.addEventListener('rest', restore);
      }
    }

    const focusId = activeNodeId ?? exploreNodeId;
    const focus = focusId ? graph.byId.get(focusId) : undefined;
    if (focus) {
      const index = route.findIndex((n) => n.id === focus.id);
      const ahead =
        index >= 0 ? (route[index + 1] ?? route[index - 1]) : undefined;
      const [x, , z] = enuToWorld(focus.enu[0], focus.enu[1]);
      let dx = 0;
      let dz = -1;
      if (ahead) {
        const [ax, , az] = enuToWorld(ahead.enu[0], ahead.enu[1]);
        const sign = route[index + 1] ? 1 : -1;
        const len = Math.hypot(ax - x, az - z) || 1;
        dx = ((ax - x) / len) * sign;
        dz = ((az - z) / len) * sign;
      }
      void ctl.setLookAt(
        x - dx * 95,
        82,
        z - dz * 95,
        x + dx * 18,
        0,
        z + dz * 18,
        animate,
      );
      return;
    }
    const { centre, distance } = overview(
      hasRoute ? route : graph.nodes,
      hasRoute,
      view.current.aspect,
      view.current.fov,
      hasRoute ? [] : campusCorners,
    );
    void ctl.setLookAt(
      centre.x + distance * OVERVIEW[0],
      distance * OVERVIEW[1],
      centre.z + distance * OVERVIEW[2],
      centre.x,
      0,
      centre.z,
      animate,
    );
  }, [
    graph,
    route,
    hasRoute,
    activeNodeId,
    exploreNodeId,
    reducedMotion,
    fitRequest,
    waiting,
    playsOpening,
    measured,
    campusCorners,
  ]);

  // The opening's grade; a pass-through afterwards, so it stays mounted
  // (removing an effect recompiles the composer's pass).
  const grade = useMemo(() => new IntroGradeEffect(), []);
  useEffect(() => () => grade.dispose(), [grade]);

  return (
    <>
      <ViewOffset insets={insets} reducedMotion={reducedMotion} />
      <SkyRig sun={sky.sun} phase={sky.phase} condition={condition} />
      <SkyEnvironment phase={sky.phase} sun={sky.sun.direction} />
      {photoreal ? (
        <GoogleTiles
          token={photoreal.token}
          errorTarget={6}
          onReady={() => undefined}
          onFailure={() => undefined}
          onAttributions={photoreal.onCredits}
        />
      ) : (
        <>
          <BaseGround />
          {ground && <GroundLayer data={ground} />}
          {greenery && <Greenery data={greenery} />}
          <Buildings
            buildings={buildings}
            night={sky.phase === 'night' || sky.phase === 'twilight'}
            reducedMotion={reducedMotion}
            // Shadows would show the buildings before they have risen.
            castShadow={!assembling}
          />
        </>
      )}
      {assembling && buildings.length > 0 && (
        <OpeningClock
          onGlide={() => setGlided(true)}
          onReveal={() => onAssembleRef.current?.onReveal()}
          onDone={() => {
            setAssembling(false);
            onAssembleRef.current?.onDone();
          }}
        />
      )}
      {ribbons.map((part) => (
        <RouteRibbon
          key={part.map((n) => n.id).join()}
          graph={graph}
          nodes={part}
          reducedMotion={reducedMotion}
          onTop={Boolean(photoreal)}
        />
      ))}
      <OverlayProjector />
      {precipitation && !reducedMotion && (
        <Precipitation kind={precipitation} />
      )}

      <CameraControls
        ref={controls}
        makeDefault
        minDistance={30}
        maxDistance={1400}
        maxPolarAngle={Math.PI * 0.42}
        smoothTime={SMOOTH_S}
      />
      <EffectComposer multisampling={4} enableNormalPass={false}>
        <N8AO
          aoRadius={7}
          distanceFalloff={1.2}
          intensity={sky.phase === 'night' ? 1.2 : 1.8}
          quality="medium"
          halfRes
        />
        <primitive object={grade} />
        <Vignette offset={0.32} darkness={0.42} />
      </EffectComposer>
    </>
  );
}

/**
 * Shifts the projection so the camera target sits in the middle of the
 * uncovered part of the screen (right of the directions panel, above the 360°
 * view) at every zoom level, easing when panels open or close.
 */
function ViewOffset({
  insets,
  reducedMotion,
}: {
  insets: SceneInsets;
  reducedMotion: boolean;
}) {
  const camera = useThree((s) => s.camera) as PerspectiveCamera;
  const size = useThree((s) => s.size);
  const offset = useRef({ x: 0, y: 0, width: 0, height: 0 });
  useFrame((_, delta) => {
    const o = offset.current;
    const tx = -insets.left / 2;
    const ty = insets.bottom / 2;
    const k = reducedMotion ? 1 : 1 - Math.exp(-delta * 7);
    const x = o.x + (tx - o.x) * k;
    const y = o.y + (ty - o.y) * k;
    const settled =
      Math.abs(x - o.x) < 0.05 &&
      Math.abs(y - o.y) < 0.05 &&
      o.width === size.width &&
      o.height === size.height;
    if (settled) return;
    offset.current = { x, y, width: size.width, height: size.height };
    camera.setViewOffset(
      size.width,
      size.height,
      x,
      y,
      size.width,
      size.height,
    );
  });
  useEffect(() => () => camera.clearViewOffset(), [camera]);
  return null;
}

/** Three-quarter overview of `nodes`: the centre and the camera distance. */
/** Camera offset of the overview (from the south-east), per unit distance. */
const OVERVIEW: [number, number, number] = [0.32, 0.92, 0.62];
/** Share of the free view the framed nodes may fill. */
const FILL = 0.78;

/**
 * Three-quarter overview of `nodes`: the centre and the camera distance that
 * fits them in the free part of the screen (`aspect`, width / height right of
 * the panel and above the sheet), high enough to read the plaza.
 */
function overview(
  nodes: GraphNode[],
  route: boolean,
  aspect: number,
  fovDeg: number,
  /** More ENU points to keep in view (the campus buildings' corners). */
  extra: [number, number][] = [],
): { centre: Vector3; distance: number } {
  const points: [number, number][] = [
    ...nodes.map((n): [number, number] => [n.enu[0], n.enu[1]]),
    ...extra,
  ];
  const box = new Box3(
    new Vector3(Infinity, 0, Infinity),
    new Vector3(-Infinity, 12, -Infinity),
  );
  for (const [e, n] of points) {
    const [x, , z] = enuToWorld(e, n);
    box.expandByPoint(new Vector3(x, 0, z));
  }
  const centre = box.getCenter(new Vector3());
  // Extent across and along the view, seen from the overview direction.
  const [ox, oy, oz] = OVERVIEW;
  const flat = Math.hypot(ox, oz);
  const fx = -ox / flat;
  const fz = -oz / flat;
  let minR = Infinity;
  let maxR = -Infinity;
  let minF = Infinity;
  let maxF = -Infinity;
  for (const [e, n] of points) {
    const [x, , z] = enuToWorld(e, n);
    const r = x * -fz + z * fx;
    const f = x * fx + z * fz;
    minR = Math.min(minR, r);
    maxR = Math.max(maxR, r);
    minF = Math.min(minF, f);
    maxF = Math.max(maxF, f);
  }
  const tanV = Math.tan((fovDeg * Math.PI) / 360);
  const tanH = tanV * Math.max(0.3, aspect);
  // Depth shows foreshortened by the camera's elevation.
  const elevation = Math.sin(Math.atan2(oy, flat));
  const across = Math.max(0, maxR - minR) / 2 / (tanH * FILL);
  const along = (Math.max(0, maxF - minF) * elevation) / 2 / (tanV * FILL);
  const length = Math.hypot(ox, oy, oz);
  const distance = Math.max(
    route ? 170 : 260,
    Math.max(across, along) / length,
  );
  return { centre, distance };
}

function BaseGround() {
  return (
    <mesh rotation-x={-Math.PI / 2} receiveShadow>
      <planeGeometry args={[9000, 9000]} />
      <meshStandardMaterial color={palette.ground} roughness={1} />
    </mesh>
  );
}

/**
 * Image-based light from a gradient of the live sky, so glass reflects the
 * sky and shaded walls pick up its tint. Re-rendered when the phase or the
 * sun moves noticeably (the sun is rounded to a few degrees).
 */
function SkyEnvironment({
  phase,
  sun,
}: {
  phase: Sky['phase'];
  sun: [number, number, number];
}) {
  const night = phase === 'night' || phase === 'twilight';
  const key = `${phase}:${sun.map((v) => v.toFixed(1)).join(',')}`;
  const uniforms = useMemo(() => {
    const colors = {
      day: ['#5E8FC9', '#CFE0EE', '#8C8778'],
      golden: ['#6E86B4', '#F2CDA6', '#7E6E5C'],
      twilight: ['#1E2B4D', '#5A5F86', '#24242C'],
      night: ['#0B1222', '#1E2A44', '#121419'],
    }[phase];
    const [x, y, z] = enuToWorld(sun[0], sun[1], Math.max(sun[2], 0.05));
    return {
      uTop: { value: new Color(colors[0]) },
      uHorizon: { value: new Color(colors[1]) },
      uBottom: { value: new Color(colors[2]) },
      uSun: { value: new Vector3(x, y, z).normalize() },
      uSunGlow: { value: phase === 'night' || phase === 'twilight' ? 0 : 1 },
    };
  }, [phase, sun]);
  return (
    <Environment
      key={key}
      frames={1}
      resolution={128}
      environmentIntensity={night ? 0.35 : 0.9}
    >
      <mesh scale={100}>
        <sphereGeometry args={[1, 32, 16]} />
        <shaderMaterial
          side={BackSide}
          depthWrite={false}
          uniforms={uniforms}
          vertexShader={
            /* glsl */ `
            varying vec3 vDir;
            void main() {
              vDir = normalize(position);
              gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }`
          }
          fragmentShader={
            /* glsl */ `
            uniform vec3 uTop;
            uniform vec3 uHorizon;
            uniform vec3 uBottom;
            uniform vec3 uSun;
            uniform float uSunGlow;
            varying vec3 vDir;
            void main() {
              float h = vDir.y;
              vec3 sky = mix(uHorizon, uTop, smoothstep(0.0, 0.6, h));
              vec3 color = h > 0.0 ? sky : mix(uHorizon * 0.8, uBottom, smoothstep(0.0, -0.25, h));
              float sun = max(dot(normalize(vDir), uSun), 0.0);
              color += vec3(1.0, 0.92, 0.8) * (pow(sun, 64.0) * 6.0 + pow(sun, 6.0) * 0.35) * uSunGlow;
              gl_FragColor = vec4(color, 1.0);
            }`
          }
        />
      </mesh>
    </Environment>
  );
}

function Buildings({
  buildings,
  night,
  reducedMotion,
  castShadow,
}: {
  buildings: Building[];
  night: boolean;
  reducedMotion: boolean;
  castShadow: boolean;
}) {
  const material = useRef<MeshStandardMaterial>(null);
  // Windows fade on over dusk instead of switching.
  useFrame((_, delta) => {
    const k = reducedMotion ? 1 : 1 - Math.exp(-delta * 1.5);
    const uniforms = material.current && facadeUniforms(material.current);
    if (uniforms)
      uniforms.uNight.value += ((night ? 1 : 0) - uniforms.uNight.value) * k;
  });
  const geometry = useMemo(() => buildMassing(buildings), [buildings]);
  // Buildings hide the DOM markers behind them (OverlayProjector). The BVH
  // takes a few hundred ms for the neighbourhood: build it when the main
  // thread is idle, not in the frames the opening plays in.
  useEffect(() => {
    if (!geometry) return;
    let bvh: MeshBVH | undefined;
    const build = () => {
      bvh = new MeshBVH(geometry);
      occluders.add(bvh);
    };
    const idle =
      typeof requestIdleCallback === 'function'
        ? requestIdleCallback(build, { timeout: 4000 })
        : window.setTimeout(build, 1500);
    return () => {
      if (typeof cancelIdleCallback === 'function') cancelIdleCallback(idle);
      else window.clearTimeout(idle);
      if (bvh) occluders.delete(bvh);
      geometry.dispose();
    };
  }, [geometry]);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry} castShadow={castShadow} receiveShadow>
      <meshStandardMaterial
        ref={material}
        vertexColors
        roughness={0.86}
        metalness={0}
        envMapIntensity={0.8}
        onBeforeCompile={patchFacade}
      />
    </mesh>
  );
}
