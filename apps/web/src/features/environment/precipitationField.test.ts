import { describe, expect, it } from 'vitest';

import {
  createField,
  DEPTHS,
  resizeField,
  stepField,
} from './precipitationField';

/** A fixed sequence, so every run falls the same way. */
function seeded(seed = 1) {
  let state = seed;
  return () => {
    state = (state * 16807) % 2147483647;
    return state / 2147483647;
  };
}

describe('precipitation field', () => {
  it('scales the number of drops with the area and the intensity', () => {
    const light = createField('rain', 0.4, 0.1, seeded());
    const heavy = createField('rain', 1, 0.1, seeded());
    resizeField(light, 300, 400);
    resizeField(heavy, 300, 400);
    expect(heavy.particles.length).toBeGreaterThan(light.particles.length);
    const full = heavy.particles.length;
    resizeField(heavy, 150, 400);
    expect(heavy.particles.length).toBe(Math.round(full / 2));
  });

  it('puts most drops far away, where they are faint', () => {
    const field = createField('rain', 1, 0, seeded());
    resizeField(field, 400, 600);
    const far = field.particles.filter((p) => p.layer === 0).length;
    const near = field.particles.filter(
      (p) => p.layer === DEPTHS.rain.length - 1,
    ).length;
    expect(far).toBeGreaterThan(near);
  });

  it('keeps falling: drops that leave come back in above the top', () => {
    const field = createField('rain', 1, 0.3, seeded());
    resizeField(field, 300, 400);
    const count = field.particles.length;
    for (let i = 0; i < 600; i++) stepField(field, 1 / 60, i / 60);
    expect(field.particles).toHaveLength(count);
    for (const p of field.particles) {
      expect(p.y).toBeLessThan(400 + 2 * DEPTHS.rain.at(-1)!.size + 40);
      expect(p.x).toBeGreaterThan(-400);
      expect(p.x).toBeLessThan(700);
    }
    // Still spread over the panel, not bunched off one side.
    const inView = field.particles.filter(
      (p) => p.x >= 0 && p.x <= 300 && p.y >= 0 && p.y <= 400,
    );
    expect(inView.length).toBeGreaterThan(count * 0.5);
  });

  it('carries rain with the wind', () => {
    const field = createField('rain', 1, 0.3, seeded());
    resizeField(field, 300, 400);
    const p = field.particles[0]!;
    const [x, y] = [p.x, p.y];
    stepField(field, 0.01, 0);
    expect(p.y).toBeGreaterThan(y);
    expect(p.x).toBeGreaterThan(x);
  });

  it('lets snow fall far slower than rain', () => {
    expect(DEPTHS.snow.at(-1)!.speed).toBeLessThan(DEPTHS.rain[0]!.speed / 5);
  });
});
