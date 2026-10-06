import { describe, expect, it } from 'vitest';

import { sunAt } from './sun';

describe('sunAt', () => {
  it('stands high in the southern sky at summer noon in İstanbul', () => {
    const sun = sunAt(new Date('2026-06-21T10:00:00Z')); // 13:00 Europe/Istanbul
    expect(sun.altitude).toBeGreaterThan((60 * Math.PI) / 180);
    expect(sun.bearingDeg).toBeGreaterThan(150);
    expect(sun.bearingDeg).toBeLessThan(230);
  });

  it('is below the horizon at midnight', () => {
    expect(sunAt(new Date('2026-10-06T21:00:00Z')).altitude).toBeLessThan(0);
  });

  it('returns a unit direction vector', () => {
    const [e, n, u] = sunAt(new Date('2026-10-06T07:00:00Z')).direction;
    expect(Math.hypot(e, n, u)).toBeCloseTo(1);
  });
});
