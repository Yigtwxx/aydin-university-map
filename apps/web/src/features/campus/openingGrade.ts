import { BlendFunction, Effect } from 'postprocessing';
import { Color, Uniform } from 'three';

import { INTRO, introClock } from './opening';

const fragment = /* glsl */ `
  uniform float uLight;
  uniform vec3 uTint;
  void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
    vec3 c = inputColor.rgb;
    // A little dim and cool at first; the live colours by the end.
    vec3 dim = c * uTint * ${INTRO.lightFrom.toFixed(2)};
    float k = (uLight - ${INTRO.lightFrom.toFixed(2)}) / ${(1 - INTRO.lightFrom).toFixed(2)};
    outputColor = vec4(mix(dim, c, clamp(k, 0.0, 1.0)), inputColor.a);
  }
`;

/**
 * Grade of the opening: the frame opens up to the live map as
 * `introClock.light` goes from INTRO.lightFrom to 1 (a pass-through at 1, so
 * it can stay in the composer).
 */
export class IntroGradeEffect extends Effect {
  constructor() {
    super('IntroGradeEffect', fragment, {
      blendFunction: BlendFunction.NORMAL,
      uniforms: new Map<string, Uniform>([
        ['uLight', introClock.light],
        ['uTint', new Uniform(new Color(0.9, 0.95, 1.1))],
      ]),
    });
  }
}
