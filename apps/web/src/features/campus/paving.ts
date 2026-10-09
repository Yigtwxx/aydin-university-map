import type { Material } from 'three';

/**
 * Paving laid on a terrace top (the `paving` vertex attribute of the masonry
 * mesh): none, small setts in running bond, or the plaza's fan cobbles.
 */
export const PAVE = { none: 0, setts: 1, fan: 2 } as const;
export type Pave = (typeof PAVE)[keyof typeof PAVE];

/**
 * Terraces paved in fans of cobblestones (*coda di pavone*, the plaza in
 * docs/design-system.md): the central square and the raised gate plaza.
 */
export const FAN_PAVED: ReadonlySet<string> = new Set(['square', 'gate-plaza']);

/** Radius of one fan and the size of its stones, metres. */
export const FAN_R_M = 1.2;
export const FAN_STONE_M = 0.12;
/** Setts: length and width of one block, metres. */
export const SETT_M = [0.4, 0.2] as const;

/** Terrace-top paving for a terrace id. */
export function paveOf(terraceId: string): Pave {
  return FAN_PAVED.has(terraceId) ? PAVE.fan : PAVE.setts;
}

const f = (n: number) => n.toFixed(4);

const PAVING_GLSL = /* glsl */ `
varying float vPaving;
varying vec2 vPaveXZ;

float paveHash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

// Joint mask (1 on the joint) of a unit cell coordinate, antialiased.
float paveJoint(vec2 cell, vec2 fw, float gap) {
  vec2 lo = smoothstep(vec2(0.0), fw * 1.5 + gap, cell);
  vec2 hi = 1.0 - smoothstep(1.0 - fw * 1.5 - gap, vec2(1.0), cell);
  return 1.0 - lo.x * lo.y * hi.x * hi.y;
}

// Small setts in running bond: a tone change per block and dark joints,
// faded out before they get smaller than a pixel.
float paveSetts(vec2 p) {
  vec2 s = p / vec2(${f(SETT_M[0])}, ${f(SETT_M[1])});
  s.x += mod(floor(s.y), 2.0) * 0.5;
  vec2 fw = fwidth(s);
  float fade = 1.0 - smoothstep(0.16, 0.42, max(fw.x, fw.y));
  float joint = paveJoint(fract(s), fw, 0.035);
  float tone = paveHash(floor(s)) - 0.5;
  return 1.0 + fade * (tone * 0.07 - joint * 0.13);
}

// Fan cobbles: overlapping half-discs in rows half a radius apart, each laid
// in rings of small stones. The highest fan whose disc holds the point wins,
// so every fan's arc shows over the row below.
float paveFan(vec2 p) {
  vec2 q = p / ${f(FAN_R_M)};
  vec2 centre = vec2(0.0);
  float found = 0.0;
  float top = floor(q.y * 2.0);
  for (int k = 0; k < 3; k++) {
    float j = top - float(k);
    float off = mod(j, 2.0);
    float i = floor((q.x - off) * 0.5 + 0.5);
    vec2 c = vec2(2.0 * i + off, j * 0.5);
    if (found < 0.5 && distance(q, c) <= 1.0) {
      centre = c;
      found = 1.0;
    }
  }
  vec2 v = (q - centre) * ${f(FAN_R_M)};
  float d = length(v);
  float ring = d / ${f(FAN_STONE_M)};
  float rings = ${f(FAN_R_M / FAN_STONE_M)};
  float k = floor(ring);
  // Stones per ring keep about square along the arc.
  float n = max(2.0, floor(3.14159 * (k + 0.5)));
  float a = atan(v.x, max(v.y, 1e-4)) / 3.14159 + 0.5;
  vec2 cell = vec2(fract(ring), fract(a * n));
  vec2 fw = vec2(fwidth(ring), fwidth(a * n));
  float stoneFade = 1.0 - smoothstep(0.18, 0.45, fw.x);
  float joint = paveJoint(cell, fw, 0.05);
  float tone = paveHash(vec2(k, floor(a * n)) + centre * 7.0) - 0.5;
  // Each fan's outer course is a touch darker, so the scallops still read a
  // little after the single stones have faded.
  float fq = fwidth(d / ${f(FAN_R_M)});
  float arcFade = 1.0 - smoothstep(0.08, 0.22, fq);
  float rim = smoothstep(rings - 1.0 - fw.x, rings - 1.0 + fw.x, ring);
  return 1.0
    + stoneFade * (tone * 0.09 - joint * 0.16)
    - arcFade * rim * 0.04 * found;
}
`;

/**
 * Draws the paving into a vertex-coloured standard material: setts on most
 * terrace tops, the fan cobbles on the plaza. Faces without the attribute's
 * pattern stay plain.
 */
export function patchPaving(material: Material): void {
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        `#include <common>
attribute float paving;
varying float vPaving;
varying vec2 vPaveXZ;`,
      )
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>
vPaving = paving;
vPaveXZ = (modelMatrix * vec4(transformed, 1.0)).xz;`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\n${PAVING_GLSL}`)
      .replace(
        '#include <color_fragment>',
        `#include <color_fragment>
if (vPaving > 1.5) diffuseColor.rgb *= paveFan(vPaveXZ);
else if (vPaving > 0.5) diffuseColor.rgb *= paveSetts(vPaveXZ);`,
      );
  };
  material.customProgramCacheKey = () => 'campus-paving';
}
