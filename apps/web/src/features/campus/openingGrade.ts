import { BlendFunction, Effect } from 'postprocessing';
import { Color, Uniform } from 'three';

import { INTRO, introClock } from './opening';

const fragment = /* glsl */ `
  uniform float uLight;
  uniform vec3 uTint;
  void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
    vec3 c = inputColor.rgb;
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    // The dots, lifted by 1 / light (OpeningPoints.tsx), take the plain light
    // factor and keep their colour.
    float lifted = smoothstep(0.9, 2.2, l);
    // The scene goes dusk blue and mostly grey; bright day scenes darker
    // still, so day and night openings both start from the dark.
    float sceneK = ${INTRO.lightFrom.toFixed(2)} / (1.0 + 5.0 * min(l, 1.0));
    vec3 scene = mix(vec3(l), c, 0.4) * uTint * sceneK;
    vec3 dim = mix(scene, c * ${INTRO.lightFrom.toFixed(2)}, lifted);
    float k = (uLight - ${INTRO.lightFrom.toFixed(2)}) / ${(1 - INTRO.lightFrom).toFixed(2)};
    outputColor = vec4(mix(dim, c, clamp(k, 0.0, 1.0)), inputColor.a);
  }
`;

/**
 * Grade of the opening: the frame starts dim and blue and opens up to the
 * live map as `introClock.light` goes from INTRO.lightFrom to 1 (a
 * pass-through at 1, so it can stay in the composer).
 * The points divide by the same factor, so they stay at full brightness.
 */
export class IntroGradeEffect extends Effect {
  constructor() {
    super('IntroGradeEffect', fragment, {
      blendFunction: BlendFunction.NORMAL,
      uniforms: new Map<string, Uniform>([
        ['uLight', introClock.light],
        ['uTint', new Uniform(new Color(0.62, 0.78, 1.25))],
      ]),
    });
  }
}
