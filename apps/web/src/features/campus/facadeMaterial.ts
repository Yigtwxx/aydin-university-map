import {
  type Material,
  Vector4,
  type WebGLProgramParametersWithUniforms,
} from 'three';

import { STYLE_INDEX } from './massing';

/** Uniforms the facade patch adds; reach them via `facadeUniforms`. */
export interface FacadeUniforms {
  /** 0 by day, 1 at night (windows light up). */
  uNight: { value: number };
}

/** The patched shader's uniforms, once the material has compiled. */
export function facadeUniforms(material: Material): FacadeUniforms | undefined {
  return material.userData.facade as FacadeUniforms | undefined;
}

/**
 * Per-style facade recipe, four vec4s each:
 *   a: bay width m, window width share, window height share, sill share
 *   b: glass rgb, frame darkening
 *   c: ribbon windows (0/1), corrugated cladding (0/1), balcony share, plinth (0/1)
 *   d: lit share at night, light intensity, warmth (0 cool .. 1 warm), floodlit (0/1)
 */
interface Recipe {
  a: [number, number, number, number];
  b: [number, number, number, number];
  c: [number, number, number, number];
  d: [number, number, number, number];
}

const GLASS_WARM: [number, number, number] = [0.3, 0.36, 0.42];
const GLASS_BLUE: [number, number, number] = [0.26, 0.38, 0.48];
const GLASS_TEAL: [number, number, number] = [0.22, 0.34, 0.37];

const RECIPES: Record<keyof typeof STYLE_INDEX, Recipe> = {
  campus: {
    a: [3.2, 0.5, 0.56, 0.3],
    b: [...GLASS_WARM, 0.25],
    c: [0, 0, 0, 1],
    d: [0.42, 1.0, 0.8, 0],
  },
  apartment: {
    a: [3.3, 0.42, 0.52, 0.3],
    b: [...GLASS_WARM, 0.2],
    c: [0, 0, 0.32, 0],
    d: [0.56, 1.05, 1.0, 0],
  },
  house: {
    a: [3.0, 0.36, 0.48, 0.32],
    b: [...GLASS_WARM, 0.2],
    c: [0, 0, 0, 0],
    d: [0.5, 1.0, 1.0, 0],
  },
  retail: {
    a: [6.0, 0.22, 0.3, 0.45],
    b: [...GLASS_TEAL, 0.1],
    c: [0, 0, 0, 0],
    d: [0.85, 1.25, 0.7, 0],
  },
  showroom: {
    a: [2.2, 0.92, 0.9, 0.06],
    b: [...GLASS_BLUE, 0.05],
    c: [0, 0, 0, 0],
    d: [0.95, 1.4, 0.15, 0],
  },
  office: {
    a: [1.6, 0.94, 0.56, 0.3],
    b: [...GLASS_BLUE, 0.05],
    c: [1, 0, 0, 0],
    d: [0.38, 1.0, 0.2, 0],
  },
  industrial: {
    a: [7.5, 0.6, 0.14, 0.78],
    b: [0.4, 0.45, 0.5, 0.0],
    c: [0, 1, 0, 0],
    d: [0.08, 0.7, 0.2, 0],
  },
  hangar: {
    a: [9.0, 0.7, 0.1, 0.84],
    b: [0.42, 0.48, 0.54, 0.0],
    c: [0, 1, 0, 0],
    d: [0.12, 0.8, 0.1, 0],
  },
  school: {
    a: [3.6, 0.56, 0.6, 0.26],
    b: [...GLASS_WARM, 0.3],
    c: [0, 0, 0, 1],
    d: [0.12, 0.9, 0.4, 0],
  },
  dormitory: {
    a: [3.0, 0.4, 0.55, 0.28],
    b: [...GLASS_WARM, 0.25],
    c: [0, 0, 0.18, 0],
    d: [0.62, 1.0, 0.9, 0],
  },
  worship: {
    a: [3.4, 0.3, 0.62, 0.22],
    b: [0.3, 0.4, 0.46, 0.15],
    c: [0, 0, 0, 1],
    d: [0.5, 0.9, 1.0, 1],
  },
  hospital: {
    a: [2.4, 0.62, 0.5, 0.32],
    b: [...GLASS_BLUE, 0.1],
    c: [0, 0, 0, 0],
    d: [0.72, 1.1, 0.1, 0],
  },
  hotel: {
    a: [3.6, 0.7, 0.66, 0.2],
    b: [...GLASS_BLUE, 0.15],
    c: [0, 0, 0.5, 0],
    d: [0.62, 1.1, 0.85, 0],
  },
  sports: {
    a: [8.0, 0.8, 0.18, 0.7],
    b: [0.32, 0.42, 0.5, 0.0],
    c: [1, 0, 0, 0],
    d: [0.3, 0.9, 0.2, 0],
  },
  canopy: {
    a: [1, 0, 0, 0],
    b: [0.3, 0.3, 0.3, 0],
    c: [0, 0, 0, 0],
    d: [0, 0, 0, 1],
  },
  fixture: {
    a: [1, 0, 0, 0],
    b: [0.3, 0.3, 0.3, 0],
    c: [0, 0, 0, 0],
    d: [0, 0, 0, 0],
  },
};

const STYLE_COUNT = Object.keys(STYLE_INDEX).length;

function recipeArrays(): Record<'a' | 'b' | 'c' | 'd', Vector4[]> {
  const arrays = {
    a: [] as Vector4[],
    b: [] as Vector4[],
    c: [] as Vector4[],
    d: [] as Vector4[],
  };
  const byIndex = Object.entries(STYLE_INDEX).sort((x, y) => x[1] - y[1]);
  for (const [style] of byIndex) {
    const recipe = RECIPES[style as keyof typeof STYLE_INDEX];
    arrays.a.push(new Vector4(...recipe.a));
    arrays.b.push(new Vector4(...recipe.b));
    arrays.c.push(new Vector4(...recipe.c));
    arrays.d.push(new Vector4(...recipe.d));
  }
  return arrays;
}

/**
 * `onBeforeCompile` for the styled massing (massing.ts). Walls get windows
 * fitted to each wall (whole bays, centred, so corners never cut a window),
 * storeys from the building's own storey height, a plinth, balconies, shop
 * fronts at street level, ribbon glazing or corrugated cladding per style,
 * and glass that reflects the environment. Roofs get tile courses (pitched)
 * or a faint concrete grain (flat). At night windows light up per building
 * and per style; mosques are floodlit.
 */
export function patchFacade(
  this: Material,
  shader: WebGLProgramParametersWithUniforms,
): void {
  const uniforms: FacadeUniforms = { uNight: { value: 0 } };
  this.userData.facade = uniforms;
  const recipes = recipeArrays();
  shader.uniforms.uNight = uniforms.uNight;
  shader.uniforms.uStyleA = { value: recipes.a };
  shader.uniforms.uStyleB = { value: recipes.b };
  shader.uniforms.uStyleC = { value: recipes.c };
  shader.uniforms.uStyleD = { value: recipes.d };

  shader.vertexShader = shader.vertexShader
    .replace(
      '#include <common>',
      `#include <common>
        attribute vec4 aWall;
        attribute vec4 aMeta;
        attribute float aFlags;
        varying vec4 vWall;
        flat varying vec4 vMeta;
        flat varying float vFlags;
        varying vec3 vFacadePos;
        varying vec3 vFacadeNormal;`,
    )
    .replace(
      '#include <project_vertex>',
      `#include <project_vertex>
        vWall = aWall;
        vMeta = aMeta;
        vFlags = aFlags;
        vFacadePos = (modelMatrix * vec4(transformed, 1.0)).xyz;
        vFacadeNormal = normalize(mat3(modelMatrix) * objectNormal);`,
    );

  shader.fragmentShader = shader.fragmentShader
    .replace(
      '#include <common>',
      `#include <common>
        uniform float uNight;
        uniform vec4 uStyleA[${STYLE_COUNT}];
        uniform vec4 uStyleB[${STYLE_COUNT}];
        uniform vec4 uStyleC[${STYLE_COUNT}];
        uniform vec4 uStyleD[${STYLE_COUNT}];
        varying vec4 vWall;
        flat varying vec4 vMeta;
        flat varying float vFlags;
        varying vec3 vFacadePos;
        varying vec3 vFacadeNormal;

        float facadeHash(vec2 p) {
          return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
        }
        // Anti-aliased box: 1 inside [lo, hi] on both axes.
        float facadeBox(vec2 f, vec2 lo, vec2 hi, float aa) {
          vec2 a = smoothstep(lo - aa, lo + aa, f);
          vec2 b = 1.0 - smoothstep(hi - aa, hi + aa, f);
          return a.x * a.y * b.x * b.y;
        }`,
    )
    .replace(
      '#include <emissivemap_fragment>',
      `#include <emissivemap_fragment>
        {
          int style = int(vMeta.x + 0.5);
          vec4 A = uStyleA[style];
          // Every building varies its window rhythm a little.
          float seedA = vMeta.y;
          A.x *= 0.86 + 0.32 * fract(seedA * 13.7);
          A.y *= 0.86 + 0.28 * fract(seedA * 7.3);
          A.z *= 0.9 + 0.18 * fract(seedA * 3.1);
          vec4 B = uStyleB[style];
          vec4 C = uStyleC[style];
          vec4 D = uStyleD[style];
          float seed = vMeta.y;
          float storeys = vMeta.z;
          float groundH = vMeta.w;
          float storey = vWall.w;
          vec3 n = normalize(vFacadeNormal);
          float glass = 0.0;
          float lit = 0.0;
          float shopLit = 0.0;

          if (abs(n.y) < 0.5 && storey > 0.0 && vWall.y > 1.6) {
            // ---- walls ----
            float u = vWall.x;
            float len = vWall.y;
            float v = vWall.z;
            float bays = max(1.0, floor(len / A.x + 0.35));
            float bayW = len / bays;
            float bx = u / bayW;
            // Storey index: the ground floor is groundH tall, the rest storey.
            float above = v - groundH;
            float level = above < 0.0 ? 0.0 : 1.0 + floor(above / storey);
            float fy = above < 0.0 ? v / groundH : fract(above / storey);
            vec2 f = vec2(fract(bx), fy);
            vec2 cell = vec2(floor(bx), level);
            float aa = max(fwidth(bx), fwidth(v / storey)) * 1.2;
            float fade = 1.0 - smoothstep(0.16, 0.42, aa);
            bool topped = level > storeys + 0.5;

            vec3 wall = diffuseColor.rgb;
            // Plinth and cornice bands (stone / brick-red on the campus).
            if (C.w > 0.5) {
              float plinth = 1.0 - smoothstep(0.85, 0.95, v);
              vec3 band = style == 0 ? vec3(0.62, 0.27, 0.19) : wall * 0.82;
              wall = mix(wall, band, plinth);
            }
            // Slab edges: light floor bands on some residential blocks.
            bool banded = (style == 1 || style == 9 || style == 12) && fract(seed * 5.7) < 0.4;
            if (banded && level > 0.5 && !topped) {
              float slab = 1.0 - smoothstep(0.05, 0.05 + aa + 0.02, fy);
              wall = mix(wall, min(wall * 1.12 + 0.05, vec3(1.0)), slab);
            }
            // Corrugated metal: vertical ribs every 0.3 m shade the panel.
            if (C.y > 0.5) {
              float rib = sin(u * 20.94) * 0.5 + 0.5;
              wall *= 0.93 + 0.07 * rib;
            }

            float win = 0.0;
            if (!topped) {
              float shopFront = level < 0.5 && vFlags > 0.5 ? 1.0 : 0.0;
              if (shopFront > 0.5) {
                // Shop front: tall glazing under a signage fascia.
                win = facadeBox(f, vec2(0.06, 0.06), vec2(0.94, 0.74), aa);
                float fascia = facadeBox(f, vec2(0.0, 0.8), vec2(1.0, 0.97), aa);
                vec3 sign = mix(vec3(0.16, 0.2, 0.26), vec3(0.62, 0.18, 0.14), step(0.6, facadeHash(cell + seed)));
                wall = mix(wall, sign, fascia * 0.85);
                shopLit = win;
              } else if (C.x > 0.5) {
                // Ribbon glazing: continuous bands with thin mullions.
                float band = facadeBox(vec2(0.5, f.y), vec2(0.0, A.w), vec2(1.0, A.w + A.z), aa);
                float mullion = 1.0 - facadeBox(vec2(f.x, 0.5), vec2(0.03, 0.0), vec2(0.97, 1.0), aa) * 1.0;
                win = band * (1.0 - mullion * 0.8);
              } else {
                float hw = A.y * 0.5;
                win = facadeBox(f, vec2(0.5 - hw, A.w), vec2(0.5 + hw, A.w + A.z), aa);
                // Balconies: a recess with a light rail on some bays.
                if (C.z > 0.0 && level > 0.5) {
                  float h = facadeHash(cell * 1.7 + seed * 31.0);
                  if (h < C.z) {
                    float recess = facadeBox(f, vec2(0.12, 0.04), vec2(0.88, 0.86), aa);
                    float rail = facadeBox(f, vec2(0.1, 0.32), vec2(0.9, 0.38), aa);
                    wall = mix(wall, wall * 0.62, recess);
                    wall = mix(wall, vec3(0.93), rail * 0.9);
                    win = max(win * 0.85, facadeBox(f, vec2(0.22, 0.38), vec2(0.78, 0.84), aa));
                  }
                }
              }
              // Window frames: a thin darker outline around the glass.
              float frame = win * (1.0 - facadeBox(f, vec2(0.5 - A.y * 0.5 + 0.02, A.w + 0.02), vec2(0.5 + A.y * 0.5 - 0.02, A.w + A.z - 0.02), aa));
              wall = mix(wall, wall * (1.0 - B.w), frame * 0.6);
            }
            win *= fade;
            glass = win;
            vec3 pane = B.rgb * (0.85 + 0.3 * facadeHash(cell + seed * 7.0));
            diffuseColor.rgb = mix(wall, pane, win * (1.0 - uNight * 0.5));
            float id = facadeHash(cell + vec2(seed * 91.0, seed * 17.0));
            lit = win * step(1.0 - D.x, id);
          } else if (abs(n.y) >= 0.5 && n.y > 0.0) {
            // ---- roofs ----
            if (n.y < 0.985) {
              // Pitched tiles: courses every 0.34 m up the slope.
              float course = fract(vFacadePos.y / 0.34);
              float ca = fwidth(vFacadePos.y / 0.34) * 1.5;
              float line = smoothstep(0.0, ca + 0.08, course) * (1.0 - smoothstep(0.9 - ca, 1.0, course));
              diffuseColor.rgb *= 0.86 + 0.14 * line;
            } else {
              float grain = facadeHash(floor(vFacadePos.xz * 1.5));
              diffuseColor.rgb *= 0.96 + 0.05 * grain;
            }
          }

          // Glass: smooth and metallic so it mirrors the sky environment.
          roughnessFactor = mix(roughnessFactor, 0.12, glass);
          metalnessFactor = mix(metalnessFactor, 0.55, glass * (1.0 - uNight));

          vec3 warm = vec3(1.0, 0.74, 0.42);
          vec3 cool = vec3(0.82, 0.9, 1.0);
          vec3 light = mix(cool, warm, D.z);
          totalEmissiveRadiance += light * lit * uNight * D.y * 1.15;
          totalEmissiveRadiance += warm * shopLit * uNight * 1.3;
          if (D.w > 0.5 && abs(n.y) < 0.5) {
            // Floodlights wash the walls from below.
            float wash = 1.0 - smoothstep(0.0, 14.0, vFacadePos.y);
            totalEmissiveRadiance += vec3(1.0, 0.82, 0.58) * wash * uNight * 0.55;
          }
        }`,
    );
}
