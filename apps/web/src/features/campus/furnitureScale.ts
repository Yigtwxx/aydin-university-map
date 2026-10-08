import {
  type Material,
  MeshDepthMaterial,
  type MeshStandardMaterial,
  RGBADepthPacking,
  Vector2,
  Vector3,
} from 'three';

/** A class of street furniture, by how big it stands. */
export type FurnitureClass = 'small' | 'medium' | 'large';

/**
 * Cartographic scale: past `from` metres from the camera each object grows in
 * proportion to the distance, up to `max` times its size, so the overview
 * still shows the café tables and benches a walker sees instead of losing
 * them below a pixel. Its height grows half as fast, so lamp posts do not
 * tower over the doors they light.
 */
export const GROW = {
  /** Chairs, tables, bins, bollards, bike racks. */
  small: { from: 150, max: 3 },
  /** Benches, planters, hedges, signs. */
  medium: { from: 280, max: 2.2 },
  /** Big or tall already: lamps, flagpoles, umbrellas, kiosks, statues. */
  large: { from: 480, max: 1.8 },
} as const satisfies Record<FurnitureClass, { from: number; max: number }>;

/**
 * Camera distances (m) over which each class finally dissolves away, well past
 * the distance its growth tops out at; the fog has the rest.
 */
export const FADE = {
  small: [900, 1300],
  medium: [1100, 1500],
  large: [1300, 1800],
  /** Handrails: lines a few centimetres thin, which never grow. */
  rails: [280, 430],
  /** Light pools under the lamps at night. */
  pools: [650, 950],
} as const satisfies Record<string, readonly [number, number]>;

/** The scale factor an object `distance` metres away is drawn at. */
export function growAt(distance: number, cls: FurnitureClass): number {
  const { from, max } = GROW[cls];
  return Math.min(max, Math.max(1, distance / from));
}

/** Where the camera is, for every material that grows; set once a frame. */
export interface Viewer {
  value: Vector3;
}

export function makeViewer(): Viewer {
  return { value: new Vector3() };
}

/**
 * Scales an instance about its own foot (its local origin) by its distance
 * to the viewer: the plan by the full factor, the height by half of it.
 * Mirrors `growAt`. Objects drawn without instancing stay as they are.
 */
const GROW_VERTEX = /* glsl */ `#include <begin_vertex>
#ifdef USE_INSTANCING
	vec3 growOrigin = (modelMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
	float growK = clamp(distance(growOrigin, uViewer) / uGrow.x, 1.0, uGrow.y);
	transformed.xz *= growK;
	transformed.y *= 1.0 + (growK - 1.0) * 0.5;
#endif`;

function patchGrow(
  material: Material,
  viewer: Viewer,
  cls: FurnitureClass,
  extra?: (shader: {
    vertexShader: string;
    fragmentShader: string;
    uniforms: Record<string, { value: unknown }>;
  }) => void,
) {
  const grow = { value: new Vector2(GROW[cls].from, GROW[cls].max) };
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uViewer = viewer;
    shader.uniforms.uGrow = grow;
    shader.vertexShader = `uniform vec3 uViewer;\nuniform vec2 uGrow;\n${shader.vertexShader.replace(
      '#include <begin_vertex>',
      GROW_VERTEX,
    )}`;
    extra?.(shader);
  };
}

/**
 * Grows the instances of a furniture class with distance and dissolves its
 * fragments between `fade`'s near and far (the class's FADE by default) with
 * a screen-space dither (no transparency, so no sorting), dropping them past
 * it.
 */
export function cartographic(
  material: MeshStandardMaterial,
  viewer: Viewer,
  cls: FurnitureClass,
  [near, far]: readonly [number, number] = FADE[cls],
): MeshStandardMaterial {
  const fade = { value: new Vector2(near, far) };
  patchGrow(material, viewer, cls, (shader) => {
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
  });
  material.customProgramCacheKey = () => `furniture-${cls}-${near}`;
  return material;
}

/** The shadow-map twin of `cartographic`: casts the grown shape's shadow. */
export function cartographicDepth(
  viewer: Viewer,
  cls: FurnitureClass,
): MeshDepthMaterial {
  const material = new MeshDepthMaterial({ depthPacking: RGBADepthPacking });
  patchGrow(material, viewer, cls);
  material.customProgramCacheKey = () => `furniture-depth-${cls}`;
  return material;
}
