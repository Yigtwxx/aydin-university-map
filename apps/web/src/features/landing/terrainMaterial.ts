import {
  Color,
  DataTexture,
  RGBAFormat,
  type ShaderMaterial,
  type Texture,
  UniformsLib,
  UniformsUtils,
  Vector2,
  Vector3,
  Vector4,
} from 'three';

import { CLOUD_GLSL } from './cloudTexture';
import type { EarthLevel } from './earth';

const LEVEL_GLSL = /* glsl */ `
  uniform vec4 uFrame0;
  uniform vec4 uFrame1;
  uniform vec4 uFrame2;
  vec2 uvOf(vec4 F, vec2 en) { return (en - F.xy) / F.z + 0.5; }
  // 1 well inside a level, 0 outside, fading over the outer edge share.
  float coverage(vec4 F, vec2 en, float edge) {
    if (F.z <= 0.0) return 0.0;
    vec2 uv = uvOf(F, en);
    vec2 d = min(uv, 1.0 - uv);
    return smoothstep(0.0, edge, min(d.x, d.y));
  }
`;

const vertexShader = /* glsl */ `
  uniform sampler2D uHeight0;
  uniform sampler2D uHeight1;
  uniform sampler2D uHeight2;
  uniform vec2 uCentre;
  uniform float uHeightScale;
  uniform float uOriginHeight;
  uniform float uFlatRadius;
  uniform float uLift;
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying vec2 vEN;
  ${LEVEL_GLSL}

  float decode(vec3 c) {
    c = floor(c * 255.0 + 0.5);
    return c.r * 256.0 + c.g + c.b / 256.0 - 32768.0;
  }
  // Manual bilinear: encoded heights must not be filtered.
  float heightIn(sampler2D t, vec4 F, vec2 en) {
    if (F.z <= 0.0) return 0.0;
    float px = F.w;
    vec2 g = clamp(uvOf(F, en), 0.0, 1.0) * px - 0.5;
    vec2 i = floor(g);
    vec2 f = g - i;
    float s = 1.0 / px;
    float h00 = decode(texture(t, (i + vec2(0.5, 0.5)) * s).rgb);
    float h10 = decode(texture(t, (i + vec2(1.5, 0.5)) * s).rgb);
    float h01 = decode(texture(t, (i + vec2(0.5, 1.5)) * s).rgb);
    float h11 = decode(texture(t, (i + vec2(1.5, 1.5)) * s).rgb);
    return mix(mix(h00, h10, f.x), mix(h01, h11, f.x), f.y);
  }
  float groundHeight(vec2 en) {
    float h = heightIn(uHeight0, uFrame0, en);
    float w1 = coverage(uFrame1, en, 0.03);
    if (w1 > 0.0) h = mix(h, heightIn(uHeight1, uFrame1, en), w1);
    float w2 = coverage(uFrame2, en, 0.06);
    if (w2 > 0.0) h = mix(h, heightIn(uHeight2, uFrame2, en), w2);
    float y = (max(h, 0.0) - uOriginHeight) * uHeightScale;
    // The campus plate is flat: the 3D map has its ground at 0.
    float r = length(en);
    return mix(0.0, y, smoothstep(uFlatRadius * 0.55, uFlatRadius, r));
  }

  void main() {
    vec3 local = position;
    vec2 xz = local.xz + uCentre;
    vec2 en = vec2(xz.x, -xz.y);
    float y = groundHeight(en);
    // Normal from central differences, wider far from the grid centre.
    float d = max(12.0, length(local.xz) * 0.006);
    float hx = groundHeight(en + vec2(d, 0.0)) - groundHeight(en - vec2(d, 0.0));
    float hn = groundHeight(en + vec2(0.0, d)) - groundHeight(en - vec2(0.0, d));
    vNormal = normalize(vec3(-hx, 2.0 * d, hn));
    vEN = en;
    vec4 world = modelMatrix * vec4(xz.x, y + uLift, xz.y, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const fragmentShader = /* glsl */ `
  uniform sampler2D uDay0;
  uniform sampler2D uDay1;
  uniform sampler2D uDay2;
  uniform sampler2D uNight0;
  uniform sampler2D uNight1;
  uniform sampler2D uNight2;
  uniform sampler2D uWater0;
  uniform sampler2D uWater1;
  uniform sampler2D uWater2;
  uniform vec3 uShore;
  uniform vec3 uSunDir;
  uniform vec3 uSunColor;
  uniform float uNightMix;
  uniform float uTime;
  uniform vec3 uHazeColor;
  uniform float uHazeDensity;
  uniform vec3 uSkyTop;
  uniform vec3 uSkyHorizon;
  uniform float uMapBlend;
  uniform vec3 uMapGround;
  uniform float uCloudScale;
  uniform vec2 uWind;
  uniform float uCloudHeight;
  uniform float uCoverage;
  uniform float uCloudShadow;
  uniform float uLightsOnly;
  uniform float uWaterOnly;
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying vec2 vEN;
  ${LEVEL_GLSL}
  ${CLOUD_GLSL}

  struct Ground { vec3 day; vec3 night; vec3 halo; float water; float shore; };

  Ground sampleGround(vec2 en) {
    Ground g;
    vec2 uv0 = uvOf(uFrame0, en);
    g.day = texture(uDay0, uv0).rgb;
    g.night = texture(uNight0, uv0).rgb;
    // A blurred read of the same lights: the glow that hangs around a city.
    g.halo = texture(uNight0, uv0, 3.0).rgb;
    vec2 w0 = texture(uWater0, uv0).rg;
    g.water = w0.r;
    g.shore = w0.g * uShore.x;
    float c1 = coverage(uFrame1, en, 0.03);
    if (c1 > 0.0) {
      vec2 uv = uvOf(uFrame1, en);
      vec2 w = texture(uWater1, uv).rg;
      g.day = mix(g.day, texture(uDay1, uv).rgb, c1);
      g.night = mix(g.night, texture(uNight1, uv).rgb, c1);
      g.halo = mix(g.halo, texture(uNight1, uv, 4.0).rgb, c1);
      g.water = mix(g.water, w.r, c1);
      g.shore = mix(g.shore, w.g * uShore.y, c1);
    }
    float c2 = coverage(uFrame2, en, 0.06);
    if (c2 > 0.0) {
      vec2 uv = uvOf(uFrame2, en);
      vec2 w = texture(uWater2, uv).rg;
      g.day = mix(g.day, texture(uDay2, uv).rgb, c2);
      g.night = mix(g.night, texture(uNight2, uv).rgb, c2);
      g.halo = mix(g.halo, texture(uNight2, uv, 4.0).rgb, c2);
      g.water = mix(g.water, w.r, c2);
      g.shore = mix(g.shore, w.g * uShore.z, c2);
    }
    // Outside every level: open sea haze.
    float known = coverage(uFrame0, en, 0.02);
    g.day = mix(vec3(0.02, 0.05, 0.07), g.day, known);
    g.water = mix(1.0, g.water, known);
    g.shore = mix(1500.0, g.shore, known);
    return g;
  }

  vec3 skyColour(vec3 dir) {
    return mix(uSkyHorizon, uSkyTop, smoothstep(0.0, 0.55, dir.y));
  }

  // Sum of directional waves (east, north), fading those too small to see.
  vec3 waveNormal(vec2 p, float footprint) {
    vec2 slope = vec2(0.0);
    const int N = 7;
    vec2 dirs[N] = vec2[](vec2(0.94, 0.34), vec2(0.62, -0.78), vec2(-0.2, 0.98),
                          vec2(0.85, 0.53), vec2(-0.71, 0.7), vec2(0.3, -0.95), vec2(0.99, -0.1));
    float lengths[N] = float[](420.0, 160.0, 61.0, 23.0, 9.0, 3.6, 1.6);
    for (int i = 0; i < N; i++) {
      float lambda = lengths[i];
      float k = 6.2831853 / lambda;
      // Long swells stay gentle, or grazing views show regular bands.
      float amp = lambda * mix(0.012, 0.0035, smoothstep(40.0, 300.0, lambda));
      // A wave needs ~8 pixels per wavelength or it sparkles (aliasing).
      float visible = 1.0 - smoothstep(lambda * 0.06, lambda * 0.14, footprint);
      float speed = sqrt(9.81 / k);
      float phase = dot(dirs[i], p) * k + uTime * speed * k;
      slope += dirs[i] * k * amp * cos(phase) * visible;
    }
    // ENU slope -> world normal (x east, y up, z south).
    return normalize(vec3(-slope.x, 1.0, slope.y));
  }

  void main() {
    Ground g = sampleGround(vEN);
    if (uLightsOnly > 0.5) {
      // Over the photoreal city at night: only the lights, added on top.
      // Calibrated to a night photo of the city: sodium-orange streets that
      // never clip, a warm glow over dense districts, white only at the core.
      float sharp = dot(g.night, vec3(0.3, 0.5, 0.2));
      float glow = dot(g.halo, vec3(0.3, 0.5, 0.2));
      float lit = (1.0 - exp(-sharp * sharp * 1.6)) * 0.42 + (1.0 - exp(-pow(glow, 1.3) * 2.4)) * 0.2;
      lit *= uNightMix * (1.0 - g.water);
      vec3 sodium = vec3(1.0, 0.58, 0.24);
      vec3 led = vec3(1.0, 0.86, 0.66);
      vec3 lights = mix(sodium, led, smoothstep(0.55, 0.95, sharp)) * lit;
      float d = length(cameraPosition - vWorld);
      lights *= exp(-d * uHazeDensity * 0.6);
      gl_FragColor = vec4(lights, 1.0);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
      return;
    }
    vec3 V = normalize(cameraPosition - vWorld);
    vec3 L = normalize(uSunDir);
    float footprint = length(fwidth(vEN));
    float dayLight = smoothstep(-0.08, 0.12, L.y);

    // Land: graded satellite colour with gentle relief shading.
    vec3 land = g.day;
    float luma = dot(land, vec3(0.2126, 0.7152, 0.0722));
    land = mix(vec3(luma), land, 1.18) * 1.12;
    float relief = 0.78 + 0.32 * max(dot(normalize(vNormal), L), 0.0);
    land *= relief;

    // Water: depth colour (from shore distance) under a sky reflection.
    vec3 N = waveNormal(vEN, footprint);
    vec3 deep = vec3(0.006, 0.036, 0.075);
    vec3 shallow = vec3(0.022, 0.11, 0.12);
    vec3 body = mix(shallow, deep, smoothstep(30.0, 900.0, g.shore));
    // A little of the real sea colour keeps currents and sediment plumes.
    body = mix(body, g.day * 1.1, 0.14);
    // Wind slicks and current lanes: broad, soft variation of the surface.
    float slick = texture(uCloudTex, vEN / 5200.0 + vec2(0.37, 0.11)).g;
    body *= 0.85 + 0.3 * slick;
    float fresnel = 0.02 + 0.98 * pow(1.0 - max(dot(V, N), 0.0), 5.0);
    vec3 R = reflect(-V, N);
    // Looking down, the sea mirrors the high sky: floor the reflection a bit.
    float reflection = clamp(fresnel * 0.8 + 0.05, 0.0, 1.0) * (0.75 + 0.5 * slick);
    vec3 water = mix(body * (0.35 + 0.65 * dayLight), skyColour(R), reflection);
    float shininess = mix(700.0, 24.0, smoothstep(0.5, 40.0, footprint));
    float glint = pow(max(dot(R, L), 0.0), shininess) * (shininess + 8.0) / 25.0;
    water += uSunColor * glint * dayLight;
    // Surf along the shore.
    float surf = (1.0 - smoothstep(4.0, 28.0, g.shore)) * (0.55 + 0.45 * sin(g.shore * 0.6 - uTime * 1.4));
    water = mix(water, vec3(0.75, 0.8, 0.82) * dayLight, surf * 0.35 * (1.0 - smoothstep(4.0, 30.0, footprint)));

    float alpha = 1.0;
    if (uWaterOnly > 0.5) {
      // Over the photoreal tiles: only the sea, painted onto Google's flat,
      // patchy low-detail water (bridges and ships stay in front).
      alpha = smoothstep(0.35, 0.7, g.water);
      if (alpha < 0.01) discard;
      g.water = 1.0;
    }
    vec3 colour = mix(land, water, g.water);

    // The campus neighbourhood turns into the map's ground as we land.
    float plate = 1.0 - smoothstep(1150.0, 2600.0, length(vEN));
    colour = mix(colour, uMapGround * (0.6 + 0.4 * dayLight), uMapBlend * plate);

    // Cloud shadows: the cover above this point along the sun direction.
    vec2 toCloud = vWorld.xz + L.xz / max(L.y, 0.15) * (uCloudHeight - vWorld.y);
    float shadow = cloudCover(toCloud, uCloudScale, uWind, uTime, uCoverage);
    // The map plate has no clouds over it (the map below has none either).
    shadow *= 1.0 - uMapBlend * plate;
    colour *= 1.0 - shadow * uCloudShadow * dayLight;

    // Night: the city lights come on over a dark, blue-tinted land.
    vec3 night = colour * vec3(0.035, 0.045, 0.075) + g.night * g.night * 3.2 * (1.0 - g.water);
    colour = mix(colour, night, uNightMix);

    // Aerial perspective.
    float dist = length(cameraPosition - vWorld);
    float haze = 1.0 - exp(-dist * uHazeDensity);
    colour = mix(colour, uHazeColor, haze);

    gl_FragColor = vec4(colour, alpha);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

const blank = (() => {
  const t = new DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1, RGBAFormat);
  t.needsUpdate = true;
  return t;
})();

export interface TerrainUniforms {
  [name: string]: { value: unknown };
}

export function createTerrainUniforms(): TerrainUniforms {
  return UniformsUtils.merge([
    UniformsLib.common,
    {
      uFrame0: { value: new Vector4(0, 0, 0, 1) },
      uFrame1: { value: new Vector4(0, 0, 0, 1) },
      uFrame2: { value: new Vector4(0, 0, 0, 1) },
      uHeight0: { value: blank },
      uHeight1: { value: blank },
      uHeight2: { value: blank },
      uDay0: { value: blank },
      uDay1: { value: blank },
      uDay2: { value: blank },
      uNight0: { value: blank },
      uNight1: { value: blank },
      uNight2: { value: blank },
      uWater0: { value: blank },
      uWater1: { value: blank },
      uWater2: { value: blank },
      uShore: { value: new Vector3(1500, 1500, 1500) },
      uCentre: { value: new Vector2() },
      uHeightScale: { value: 1.35 },
      uOriginHeight: { value: 0 },
      uFlatRadius: { value: 1600 },
      uLift: { value: 0 },
      uSunDir: { value: new Vector3(0.4, 0.6, -0.3) },
      uSunColor: { value: new Color('#fff3e0') },
      uNightMix: { value: 0 },
      uTime: { value: 0 },
      uHazeColor: { value: new Color('#c9d8e6') },
      uHazeDensity: { value: 0.00002 },
      uSkyTop: { value: new Color('#3d6fa8') },
      uSkyHorizon: { value: new Color('#c9d8e6') },
      uMapBlend: { value: 0 },
      // The map's ground as it looks lit (MeshStandardMaterial under the sun).
      uMapGround: { value: new Color('#CBC6BC') },
      uCloudScale: { value: 5200 },
      uWind: { value: new Vector2(0.0018, 0.0007) },
      uCloudHeight: { value: 2800 },
      uCoverage: { value: 0.38 },
      uCloudShadow: { value: 0.42 },
      uLightsOnly: { value: 0 },
      uWaterOnly: { value: 0 },
      uCloudTex: { value: blank },
    },
  ]) as TerrainUniforms;
}

export const terrainShaders = { vertexShader, fragmentShader };

/** Bind loaded levels (coarse first) to the material's level slots. */
export function bindLevels(
  material: ShaderMaterial,
  levels: EarthLevel[],
  originHeight: number,
): void {
  const u = material.uniforms;
  const shore = new Vector3(1500, 1500, 1500);
  levels.slice(0, 3).forEach((level, i) => {
    (u[`uFrame${i}`]!.value as Vector4).set(...level.frame);
    u[`uHeight${i}`]!.value = level.height as Texture;
    u[`uDay${i}`]!.value = level.day;
    u[`uNight${i}`]!.value = level.night;
    u[`uWater${i}`]!.value = level.water;
    shore.setComponent(i, level.shoreMax);
  });
  u.uShore!.value = shore;
  u.uOriginHeight!.value = originHeight;
}
