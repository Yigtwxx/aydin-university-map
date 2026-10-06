import type { Material, WebGLProgramParametersWithUniforms } from 'three';

/** Uniforms the facade patch adds; reach them via `facadeUniforms`. */
export interface FacadeUniforms {
  /** 0 by day, 1 at night (windows light up). */
  uNight: { value: number };
  /** Share of windows lit at night. */
  uLitShare: { value: number };
}

/** The patched shader's uniforms, once the material has compiled. */
export function facadeUniforms(material: Material): FacadeUniforms | undefined {
  return material.userData.facade as FacadeUniforms | undefined;
}

/**
 * `onBeforeCompile` for a MeshStandardMaterial that draws window bands on
 * walls (faces whose normal is horizontal): darker glass by day, warm lit
 * windows at night. The pattern comes from world position, so the merged
 * massing stays one draw call, and it fades where it would alias (far away
 * or at grazing angles).
 */
export function patchFacade(
  this: Material,
  shader: WebGLProgramParametersWithUniforms,
): void {
  const uniforms: FacadeUniforms = {
    uNight: { value: 0 },
    uLitShare: { value: 0.58 },
  };
  this.userData.facade = uniforms;
  shader.uniforms.uNight = uniforms.uNight;
  shader.uniforms.uLitShare = uniforms.uLitShare;
  shader.vertexShader = shader.vertexShader
    .replace(
      '#include <common>',
      `#include <common>
        varying vec3 vFacadePos;
        varying vec3 vFacadeNormal;`,
    )
    .replace(
      '#include <project_vertex>',
      `#include <project_vertex>
        vFacadePos = (modelMatrix * vec4(transformed, 1.0)).xyz;
        vFacadeNormal = normalize(mat3(modelMatrix) * objectNormal);`,
    );
  shader.fragmentShader = shader.fragmentShader
    .replace(
      '#include <common>',
      `#include <common>
        uniform float uNight;
        uniform float uLitShare;
        varying vec3 vFacadePos;
        varying vec3 vFacadeNormal;`,
    )
    .replace(
      '#include <emissivemap_fragment>',
      `#include <emissivemap_fragment>
        {
          vec3 n = normalize(vFacadeNormal);
          if (abs(n.y) < 0.5) {
            vec2 tangent = normalize(vec2(-n.z, n.x));
            // Bays 3.1 m wide, storeys 3.2 m high, starting above the plinth.
            vec2 cell = vec2(dot(vFacadePos.xz, tangent) / 3.1, (vFacadePos.y - 0.9) / 3.2);
            vec2 f = fract(cell);
            vec2 w = fwidth(cell);
            float aa = max(w.x, w.y);
            float win =
              smoothstep(0.26 - aa, 0.26 + aa, f.x) * (1.0 - smoothstep(0.78 - aa, 0.78 + aa, f.x)) *
              smoothstep(0.30 - aa, 0.30 + aa, f.y) * (1.0 - smoothstep(0.80 - aa, 0.80 + aa, f.y)) *
              step(0.0, cell.y);
            win *= 1.0 - smoothstep(0.18, 0.4, aa);
            float id = fract(sin(dot(floor(cell), vec2(12.9898, 78.233))) * 43758.5453);
            diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.33, 0.40, 0.49), win * 0.5 * (1.0 - uNight * 0.6));
            totalEmissiveRadiance += vec3(1.0, 0.76, 0.42) * win * step(1.0 - uLitShare, id) * uNight * 1.1;
          }
        }`,
    );
}
