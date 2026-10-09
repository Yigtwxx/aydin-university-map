import { Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import {
  SHADOW_HALF_MAX_M,
  SHADOW_HALF_MIN_M,
  shadowHalfWidth,
  snapToTexel,
} from './shadowFit';

describe('shadowHalfWidth', () => {
  it('stays tight close up and covers the campus from afar', () => {
    expect(shadowHalfWidth(30)).toBe(SHADOW_HALF_MIN_M);
    expect(shadowHalfWidth(5000)).toBe(SHADOW_HALF_MAX_M);
  });

  it('grows with distance in a few fixed steps', () => {
    const sizes = new Set<number>();
    let last = 0;
    for (let d = 30; d <= 1400; d += 5) {
      const half = shadowHalfWidth(d);
      expect(half).toBeGreaterThanOrEqual(last);
      expect(half).toBeGreaterThanOrEqual(Math.min(d * 0.55, 420) - 1e-6);
      sizes.add(half);
      last = half;
    }
    expect(sizes.size).toBeLessThanOrEqual(8);
  });
});

describe('snapToTexel', () => {
  const sun = new Vector3(0.4, 0.8, 0.3).normalize();

  it('moves the centre by less than a texel', () => {
    const centre = new Vector3(12.34, 4, -56.78);
    const snapped = snapToTexel(centre, sun, 0.2);
    expect(snapped.distanceTo(centre)).toBeLessThan(0.2 * Math.SQRT2);
  });

  it('lands nearby centres on the same texel as the sun sees it', () => {
    const a = snapToTexel(new Vector3(10, 0, 10), sun, 0.5);
    const b = snapToTexel(new Vector3(10.01, 0, 10.01), sun, 0.5);
    // What is left differs only along the sun's rays, which the map ignores.
    const d = a.sub(b);
    const across = d.addScaledVector(sun, -d.dot(sun));
    expect(across.length()).toBeLessThan(1e-6);
  });

  it('only shifts across the sun, never along its rays', () => {
    const centre = new Vector3(3.3, 0, -7.7);
    const shift = snapToTexel(centre, sun, 0.4).sub(centre);
    expect(Math.abs(shift.dot(sun))).toBeLessThan(1e-6);
  });
});
