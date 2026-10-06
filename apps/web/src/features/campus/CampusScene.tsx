'use client';

import { CameraControls, Edges } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { EffectComposer, N8AO, Vignette } from '@react-three/postprocessing';
import { useEffect, useMemo, useRef } from 'react';
import {
  Box3,
  type MeshStandardMaterial,
  type PerspectiveCamera,
  Vector3,
} from 'three';

import type { Sky } from '@/features/environment/hooks';
import {
  type Condition,
  precipitationOf,
} from '@/features/environment/weather';
import {
  headingFromAzimuth,
  POLAR_TOP_DOWN,
  useCameraStore,
} from '@/features/map/cameraStore';

import { buildingColors, palette } from './constants';
import { enuToWorld } from './coords';
import { facadeUniforms, patchFacade } from './facadeMaterial';
import { extrudeBuildings, paintWallsAndRoofs } from './geometry';
import { Greenery } from './Greenery';
import { GroundLayer } from './GroundLayer';
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
  /** Node of the route step being previewed in 360°. */
  activeNodeId?: string;
  /** Node shown in 360° while exploring without a route. */
  exploreNodeId?: string;
  sky: Sky;
  condition?: Condition;
  reducedMotion: boolean;
}

export function CampusScene(props: SceneProps) {
  return (
    <Canvas
      shadows="percentage"
      dpr={[1, 2]}
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
  activeNodeId,
  exploreNodeId,
  sky,
  condition,
  insets,
  reducedMotion,
}: SceneProps) {
  const controls = useRef<CameraControls>(null);
  const introduced = useRef(false);
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

  // Glide in on first load, then frame the route, the step being previewed
  // (from behind the walker, facing the next node) or the whole network.
  useEffect(() => {
    const ctl = controls.current;
    if (!ctl) return;
    const animate = !reducedMotion;
    if (!introduced.current) {
      introduced.current = true;
      if (animate) {
        ctl.smoothTime = INTRO_SMOOTH_S;
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
        x - dx * 70,
        62,
        z - dz * 70,
        x + dx * 18,
        0,
        z + dz * 18,
        animate,
      );
      return;
    }
    const box = boundsOf(hasRoute ? route : graph.nodes);
    const centre = box.getCenter(new Vector3());
    const size = box.getSize(new Vector3());
    // Three-quarter view from the south-east, high enough to read the plaza.
    const distance = Math.max(
      hasRoute ? 170 : 260,
      Math.max(size.x, size.z) * 2.2,
    );
    void ctl.setLookAt(
      centre.x + distance * 0.32,
      distance * 0.92,
      centre.z + distance * 0.62,
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
  ]);

  return (
    <>
      <ViewOffset insets={insets} reducedMotion={reducedMotion} />
      <SkyRig sun={sky.sun} phase={sky.phase} condition={condition} />
      <BaseGround />
      {ground && <GroundLayer data={ground} />}
      {greenery && <Greenery data={greenery} />}
      <Buildings
        buildings={buildings}
        night={sky.phase === 'night' || sky.phase === 'twilight'}
        reducedMotion={reducedMotion}
      />
      {hasRoute && <RouteRibbon nodes={route} reducedMotion={reducedMotion} />}
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

function boundsOf(nodes: GraphNode[]): Box3 {
  const box = new Box3(
    new Vector3(Infinity, 0, Infinity),
    new Vector3(-Infinity, 12, -Infinity),
  );
  for (const n of nodes) {
    const [x, , z] = enuToWorld(n.enu[0], n.enu[1]);
    box.expandByPoint(new Vector3(x, 0, z));
  }
  return box;
}

function BaseGround() {
  return (
    <mesh rotation-x={-Math.PI / 2} receiveShadow>
      <planeGeometry args={[9000, 9000]} />
      <meshStandardMaterial color={palette.ground} roughness={1} />
    </mesh>
  );
}

function Buildings({
  buildings,
  night,
  reducedMotion,
}: {
  buildings: Building[];
  night: boolean;
  reducedMotion: boolean;
}) {
  const campusMaterial = useRef<MeshStandardMaterial>(null);
  const otherMaterial = useRef<MeshStandardMaterial>(null);
  // Windows fade on over dusk instead of switching.
  useFrame((_, delta) => {
    const k = reducedMotion ? 1 : 1 - Math.exp(-delta * 1.5);
    for (const material of [campusMaterial.current, otherMaterial.current]) {
      const uniforms = material && facadeUniforms(material);
      if (uniforms)
        uniforms.uNight.value += ((night ? 1 : 0) - uniforms.uNight.value) * k;
    }
  });
  const campus = useMemo(() => {
    const g = extrudeBuildings(buildings.filter((b) => b.campus));
    if (g)
      paintWallsAndRoofs(
        g,
        buildingColors.campusWall,
        buildingColors.campusRoof,
      );
    return g;
  }, [buildings]);
  const others = useMemo(() => {
    const g = extrudeBuildings(buildings.filter((b) => !b.campus));
    if (g)
      paintWallsAndRoofs(g, buildingColors.otherWall, buildingColors.otherRoof);
    return g;
  }, [buildings]);
  useEffect(
    () => () => {
      campus?.dispose();
      others?.dispose();
    },
    [campus, others],
  );
  return (
    <>
      {others && (
        <mesh geometry={others} castShadow receiveShadow>
          <meshStandardMaterial
            ref={otherMaterial}
            vertexColors
            roughness={0.92}
            onBeforeCompile={patchFacade}
          />
        </mesh>
      )}
      {campus && (
        <mesh geometry={campus} castShadow receiveShadow>
          <meshStandardMaterial
            ref={campusMaterial}
            vertexColors
            roughness={0.8}
            onBeforeCompile={patchFacade}
          />
          <Edges threshold={25} color={palette.edges} />
        </mesh>
      )}
    </>
  );
}
