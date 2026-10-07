import {
  type Material,
  type Texture,
  Vector4,
  type WebGLProgramParametersWithUniforms,
} from 'three';

import { INTRO, introClock } from './opening';
import { STYLE_INDEX } from './massing';

/** Uniforms the facade patch adds; reach them via `facadeUniforms`. */
export interface FacadeUniforms {
  /** 0 by day, 1 at night (windows light up). */
  uNight: { value: number };
  /**
   * Clock of the opening (opening.ts), in seconds. Buildings emerge from the
   * ground as it passes their `aRise` time; after the opening they all stand.
   */
  uIntroTime: { value: number };
  /**
   * Surveyed facade recipes of the massing (facadeRecipe.ts, from
   * `massingRecipes`); null when no block has one.
   */
  uRecipes: { value: Texture | null };
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
 *
 * Blocks with a surveyed recipe (aFlags.y > 0) draw their walls from it
 * instead: plinth, string course and cornice in the recipe's colours, punched
 * windows in moulded surrounds, ribbon bands or curtain glass per side, and a
 * glazed, solid or arcaded ground floor. Set the recipe texture before the
 * first render with `material.userData.facadeRecipes`, later through
 * `facadeUniforms(material).uRecipes`.
 */
export function patchFacade(
  this: Material,
  shader: WebGLProgramParametersWithUniforms,
): void {
  const uniforms: FacadeUniforms = {
    uNight: { value: 0 },
    uIntroTime: introClock.time,
    uRecipes: {
      value: (this.userData.facadeRecipes as Texture | undefined) ?? null,
    },
  };
  this.userData.facade = uniforms;
  const recipes = recipeArrays();
  shader.uniforms.uNight = uniforms.uNight;
  shader.uniforms.uIntroTime = uniforms.uIntroTime;
  shader.uniforms.uStyleA = { value: recipes.a };
  shader.uniforms.uStyleB = { value: recipes.b };
  shader.uniforms.uStyleC = { value: recipes.c };
  shader.uniforms.uStyleD = { value: recipes.d };
  shader.uniforms.uFacadeRecipes = uniforms.uRecipes;

  shader.vertexShader = shader.vertexShader
    .replace(
      '#include <common>',
      `#include <common>
        attribute vec4 aWall;
        attribute vec4 aMeta;
        attribute vec4 aFlags;
        attribute vec2 aRise;
        uniform float uIntroTime;
        varying vec4 vWall;
        flat varying vec4 vMeta;
        flat varying vec4 vFlags;
        varying vec3 vFacadePos;
        varying vec3 vFacadeNormal;
        varying float vRise;`,
    )
    .replace(
      '#include <begin_vertex>',
      `#include <begin_vertex>
        // Opening: the building comes up out of the ground (ease-out cubic).
        float riseK = clamp((uIntroTime - aRise.x) / ${INTRO.riseDurS.toFixed(2)}, 0.0, 1.0);
        vRise = 1.0 - pow(1.0 - riseK, 3.0);
        transformed.y -= (1.0 - vRise) * aRise.y;`,
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
        uniform float uIntroTime;
        uniform vec4 uStyleA[${STYLE_COUNT}];
        uniform vec4 uStyleB[${STYLE_COUNT}];
        uniform vec4 uStyleC[${STYLE_COUNT}];
        uniform vec4 uStyleD[${STYLE_COUNT}];
        uniform highp sampler2D uFacadeRecipes;
        varying vec4 vWall;
        flat varying vec4 vMeta;
        flat varying vec4 vFlags;
        varying vec3 vFacadePos;
        varying vec3 vFacadeNormal;
        varying float vRise;

        float facadeHash(vec2 p) {
          return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
        }
        // Anti-aliased box: 1 inside [lo, hi] on both axes.
        float facadeBox(vec2 f, vec2 lo, vec2 hi, float aa) {
          vec2 a = smoothstep(lo - aa, lo + aa, f);
          vec2 b = 1.0 - smoothstep(hi - aa, hi + aa, f);
          return a.x * a.y * b.x * b.y;
        }
        // Anti-aliased span: 1 for x inside [lo, hi].
        float facadeSpan(float x, float lo, float hi, float aa) {
          return smoothstep(lo - aa, lo + aa, x) * (1.0 - smoothstep(hi - aa, hi + aa, x));
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
          int slot = int(vFlags.y + 0.5);
          bool facadeWall = abs(n.y) < 0.5 && storey > 0.0 && vWall.y > 1.6;

          if (facadeWall && slot > 0 && vFlags.z > 3.5) {
            // ---- masonry feature (a tower): courses, a recessed panel ----
            // Here vMeta.w is the feature's base and vWall.w its height.
            float u = vWall.x;
            float len = vWall.y;
            float h = vWall.z - groundH;
            float tall = storey;
            float cw = fwidth(h / 0.3);
            float course = facadeSpan(fract(h / 0.3), 0.0, 0.12, cw) * (1.0 - smoothstep(0.12, 0.35, cw));
            vec3 wall = diffuseColor.rgb * (1.0 - 0.07 * course);
            float am = max(fwidth(u), fwidth(h)) + 0.001;
            float panel = len > 3.0 ? facadeBox(vec2(u, h), vec2(0.7, 1.2), vec2(len - 0.7, tall - 1.4), am) : 0.0;
            // The recess shades a little, deepest under its head.
            float reveal = panel * (1.0 - smoothstep(tall - 1.4 - 0.22 - am, tall - 1.4 - am, h));
            wall *= 1.0 - 0.12 * panel - 0.1 * (panel - reveal);
            wall *= 0.86 + 0.14 * smoothstep(0.34 - am, 0.34 + am, h);
            diffuseColor.rgb = wall;
          } else if (facadeWall && slot > 0) {
            // ---- surveyed walls (facadeRecipe.ts) ----
            int row = slot - 1;
            vec4 R0 = texelFetch(uFacadeRecipes, ivec2(0, row), 0);
            vec4 R1 = texelFetch(uFacadeRecipes, ivec2(1, row), 0);
            vec4 R2 = texelFetch(uFacadeRecipes, ivec2(2, row), 0);
            vec4 R3 = texelFetch(uFacadeRecipes, ivec2(3, row), 0);
            float windows = vFlags.z;
            float groundKind = vFlags.w;
            float u = vWall.x;
            float len = vWall.y;
            float v = vWall.z;
            float bays = max(1.0, floor(len / max(R0.x, 0.8) + 0.35));
            float bayW = len / bays;
            float bx = u / bayW;
            float above = v - groundH;
            bool onGround = above < 0.0;
            float level = onGround ? 0.0 : 1.0 + floor(above / storey);
            float rowH = onGround ? groundH : storey;
            float fy = onGround ? v / groundH : fract(above / storey);
            vec2 f = vec2(fract(bx), fy);
            vec2 cell = vec2(floor(bx), level);
            float aa = max(fwidth(bx), fwidth(v / rowH)) * 1.2;
            float fade = 1.0 - smoothstep(0.16, 0.42, aa);
            float av = fwidth(v) * 0.75 + 0.001;
            bool topped = level > storeys + 0.5;
            float roofLine = groundH + storeys * storey;

            vec3 wall = diffuseColor.rgb;
            // Plinth: the ground floor in its own material, laid in courses.
            float plinthK = R1.w * (1.0 - smoothstep(groundH - av, groundH + av, v));
            float course = facadeSpan(fract(v / 0.3), 0.0, 0.1, fwidth(v / 0.3));
            vec3 plinth = R1.rgb * (1.0 - 0.07 * course * (1.0 - smoothstep(0.12, 0.35, fwidth(v / 0.3))));
            wall = mix(wall, plinth, plinthK);
            // Socle: a darker base course where the wall meets the paving.
            wall *= 0.86 + 0.14 * smoothstep(0.34 - av, 0.34 + av, v);
            // String course over the ground floor, cornice at the roof line.
            float bands = facadeSpan(v, roofLine - 0.32, roofLine + 0.4, av);
            if (R1.w > 0.5 || groundKind > 0.5)
              bands = max(bands, facadeSpan(v, groundH - 0.1, groundH + 0.2, av));

            float win = 0.0;    // glass, in detail
            float cover = 0.0;  // its share of the wall, seen from afar
            float detail = 0.0; // trims round the openings
            float shop = 0.0;
            bool front = onGround && groundKind > 0.5;
            if (!topped) {
              float hx = R0.y * 0.5;
              float sill = R0.w;
              float head = R0.w + R0.z;
              // Trim width (13 cm) as a share of the bay and of the floor.
              vec2 m = vec2(0.13 / bayW, 0.13 / rowH);
              if (front) {
                if (groundKind < 1.5) {
                  // Glazed: shop fronts and lobby glass between slim piers.
                  float bay = facadeBox(f, vec2(m.x, 0.0), vec2(1.0 - m.x, 0.82), aa);
                  float glazing = facadeBox(f, vec2(m.x * 2.0, 0.02), vec2(1.0 - m.x * 2.0, 0.82 - m.y), aa);
                  float mull = facadeSpan(f.x, 0.5 - m.x * 0.4, 0.5 + m.x * 0.4, aa);
                  win = glazing * (1.0 - mull);
                  detail = bay - win;
                  cover = 0.68;
                  shop = win;
                } else if (groundKind > 2.5) {
                  // Arcade: columns on the bay lines, glass back in their shade.
                  float open = facadeBox(f, vec2(0.11, 0.0), vec2(0.89, 0.86), aa);
                  wall = mix(wall, wall * 0.48, open);
                  win = facadeBox(f, vec2(0.17, 0.05), vec2(0.83, 0.74), aa) * 0.85;
                  detail = 1.0 - facadeSpan(f.x, 0.11, 0.89, aa);
                  cover = 0.4;
                  shop = win * 0.6;
                }
                // Solid: no openings.
              } else if (windows < 0.5) {
                // Punched windows in moulded surrounds, on a projecting sill.
                win = facadeBox(f, vec2(0.5 - hx, sill), vec2(0.5 + hx, head), aa);
                float frame = facadeBox(f, vec2(0.5 - hx, sill) - m, vec2(0.5 + hx, head) + m, aa);
                float ledge = facadeBox(f, vec2(0.5 - hx - m.x * 1.8, sill - m.y * 1.7), vec2(0.5 + hx + m.x * 1.8, sill - m.y * 0.5), aa);
                // A mullion splits windows wider than 1.1 m.
                float mull = R0.y * bayW > 1.1 ? facadeSpan(f.x, 0.5 - 0.04 / bayW, 0.5 + 0.04 / bayW, aa) * win : 0.0;
                detail = max(frame - win, ledge) + mull;
                win -= mull;
                cover = R0.y * R0.z;
              } else if (windows < 1.5) {
                // Ribbon: continuous glass bands with slim mullions.
                float band = facadeSpan(f.y, sill, head, aa);
                float lines = 1.0 - facadeSpan(fract(bx * 2.0), 0.035, 0.965, aa * 2.0);
                win = band * (1.0 - lines);
                detail = band * lines + facadeSpan(f.y, sill - m.y * 0.8, sill, aa);
                cover = R0.z * 0.92;
              } else if (windows < 2.5) {
                // Curtain wall: glass floor to floor, a spandrel at each slab.
                float sp = 0.25 / rowH;
                float band = facadeSpan(f.y, sp, 1.0 - sp, aa);
                float lines = 1.0 - facadeSpan(fract(bx * 2.0), 0.025, 0.975, aa * 2.0);
                win = band * (1.0 - lines);
                detail = band * lines;
                cover = (1.0 - sp * 2.0) * 0.94;
              }
              // Blank: a closed wall.
            }
            float near = win;
            // Far away the openings blur into their average, not into wall.
            win = mix(cover, near, fade);
            wall = mix(wall, R2.rgb, max(bands, clamp(detail, 0.0, 1.0) * fade));
            glass = win;
            bool curtain = !front && windows > 1.5 && windows < 2.5;
            float tint = curtain ? 0.1 : 0.24;
            vec3 pane = R3.rgb * (1.0 - tint * 0.5 + tint * facadeHash(cell + seed * 7.0));
            if (front || windows > 0.5) {
              // Broad glazing mirrors the sky, brighter up the facade and
              // towards each pane's head, so it reads as glass, not a void.
              float rise = clamp(v / max(roofLine, 1.0), 0.0, 1.0);
              float sheen = front ? 0.1 + 0.1 * f.y : 0.16 + 0.2 * rise + 0.08 * f.y;
              pane = mix(pane, vec3(0.56, 0.67, 0.78), sheen * (1.0 - uNight));
            }
            diffuseColor.rgb = mix(wall, pane, win * (1.0 - uNight * 0.5));
            float id = facadeHash(cell + vec2(seed * 91.0, seed * 17.0));
            lit = front ? 0.0 : mix(cover * D.x, near * step(1.0 - D.x, id), fade);
            shopLit = front ? mix(cover * 0.8, shop, fade) : 0.0;
          } else if (facadeWall) {
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
              float shopFront = level < 0.5 && vFlags.x > 0.5 ? 1.0 : 0.0;
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
          // Opening: a bright seam on the walls where the rising building
          // meets the ground (roofs cross it too fast to light up cleanly).
          float rising = step(0.001, vRise) * (1.0 - vRise);
          float seam = (1.0 - smoothstep(0.0, 1.1, vFacadePos.y)) * step(abs(n.y), 0.5);
          // The intro grade dims the scene; the seam stays bright through it.
          float graded = mix(${INTRO.lightFrom.toFixed(2)}, 1.0, smoothstep(${INTRO.lightRiseFromS.toFixed(2)}, ${INTRO.lightRiseToS.toFixed(2)}, uIntroTime));
          totalEmissiveRadiance += vec3(1.0, 0.8, 0.55) * seam * rising * 0.55 / graded;
        }`,
    );
}
