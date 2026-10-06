import {
  LinearFilter,
  LinearMipmapLinearFilter,
  Mesh,
  OrthographicCamera,
  PlaneGeometry,
  RepeatWrapping,
  RGBAFormat,
  Scene,
  ShaderMaterial,
  type Texture,
  UnsignedByteType,
  WebGLRenderTarget,
  type WebGLRenderer,
} from 'three';

/** Noise lattice cells across the texture; the pattern repeats after this. */
export const CLOUD_PERIOD = 12;
const SIZE = 1024;

/**
 * The cloud field is periodic fbm with domain warping, baked once on the GPU
 * into a tiling texture. Clouds and their shadows then cost two texture reads
 * per pixel instead of ~45 noise octaves (the landing's biggest GPU cost).
 *   R: cumulus cover field, G: fine detail for ragged edges.
 */
const bakeFragment = /* glsl */ `
  uniform float uPeriod;
  varying vec2 vUv;
  float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
  }
  // Value noise whose lattice wraps every "period" cells: seamless tiles.
  float vnoise(vec2 p, float period) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash12(mod(i, period));
    float b = hash12(mod(i + vec2(1.0, 0.0), period));
    float c = hash12(mod(i + vec2(0.0, 1.0), period));
    float d = hash12(mod(i + vec2(1.0, 1.0), period));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
  }
  float fbm(vec2 p, float period) {
    float sum = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 6; i++) {
      sum += amp * vnoise(p, period);
      p *= 2.0;
      period *= 2.0;
      amp *= 0.5;
    }
    return sum;
  }
  void main() {
    vec2 p = vUv * uPeriod;
    vec2 warp = vec2(fbm(p + 3.1, uPeriod), fbm(p + vec2(5.7, 1.3), uPeriod));
    float cover = fbm(p + warp * 0.9, uPeriod);
    float detail = fbm(p * 8.0, uPeriod * 8.0);
    gl_FragColor = vec4(cover, detail, 0.0, 1.0);
  }
`;

export function bakeCloudTexture(gl: WebGLRenderer): Texture {
  const target = new WebGLRenderTarget(SIZE, SIZE, {
    format: RGBAFormat,
    type: UnsignedByteType,
    depthBuffer: false,
    generateMipmaps: true,
    minFilter: LinearMipmapLinearFilter,
    magFilter: LinearFilter,
    wrapS: RepeatWrapping,
    wrapT: RepeatWrapping,
  });
  const material = new ShaderMaterial({
    uniforms: { uPeriod: { value: CLOUD_PERIOD } },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = vec4(position.xy, 0.0, 1.0);
      }`,
    fragmentShader: bakeFragment,
    depthTest: false,
    depthWrite: false,
  });
  const quad = new Mesh(new PlaneGeometry(2, 2), material);
  const scene = new Scene();
  scene.add(quad);
  const previous = gl.getRenderTarget();
  gl.setRenderTarget(target);
  gl.render(scene, new OrthographicCamera(-1, 1, 1, -1, 0, 1));
  gl.setRenderTarget(previous);
  quad.geometry.dispose();
  material.dispose();
  return target.texture;
}

/**
 * Cloud cover at a ground position (world x, z): the baked field, drifting
 * with the wind, sharpened by ``coverage``. Needs ``uniform sampler2D
 * uCloudTex`` and ``CLOUD_PERIOD`` in the including shader.
 */
export const CLOUD_GLSL = /* glsl */ `
  uniform sampler2D uCloudTex;
  float cloudCover(vec2 xz, float scale, vec2 wind, float time, float coverage) {
    vec2 uv = (xz / scale + wind * time) / ${CLOUD_PERIOD.toFixed(1)};
    vec2 field = texture(uCloudTex, uv).rg;
    float n = field.r + (field.g - 0.5) * 0.16;
    return smoothstep(1.0 - coverage, 1.0 - coverage + 0.12, n);
  }
`;
