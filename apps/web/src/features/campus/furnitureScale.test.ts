import { describe, expect, it } from 'vitest';

import { FADE, type FurnitureClass, GROW, growAt } from './furnitureScale';

const CLASSES: FurnitureClass[] = ['small', 'medium', 'large'];

describe('growAt', () => {
  it('keeps true size up close', () => {
    for (const cls of CLASSES) {
      expect(growAt(0, cls)).toBe(1);
      expect(growAt(GROW[cls].from, cls)).toBe(1);
    }
  });

  it('grows in proportion to the distance past its start', () => {
    expect(growAt(GROW.small.from * 2, 'small')).toBeCloseTo(2);
  });

  it('tops out at its cap', () => {
    for (const cls of CLASSES)
      expect(growAt(GROW[cls].from * GROW[cls].max * 10, cls)).toBe(
        GROW[cls].max,
      );
  });
});

describe('FADE', () => {
  it('dissolves a class only once it has finished growing', () => {
    for (const cls of CLASSES)
      expect(FADE[cls][0]).toBeGreaterThan(GROW[cls].from * GROW[cls].max);
  });

  it('keeps bigger things in view longer', () => {
    expect(FADE.small[0]).toBeLessThan(FADE.medium[0]);
    expect(FADE.medium[0]).toBeLessThan(FADE.large[0]);
  });
});
