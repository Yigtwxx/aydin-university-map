import { describe, expect, it } from 'vitest';

import { tileableNoise } from './skyNoise';

const options = {
  width: 64,
  height: 32,
  cellsX: 3,
  cellsY: 2,
  octaves: 4,
  seed: 5,
};

describe('tileableNoise', () => {
  const noise = tileableNoise(options);
  const at = (x: number, y: number) => noise[y * options.width + x]!;

  it('stays within 0–1 and is not flat', () => {
    let min = 1;
    let max = 0;
    for (const v of noise) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
      min = Math.min(min, v);
      max = Math.max(max, v);
    }
    expect(max - min).toBeGreaterThan(0.3);
  });

  it('wraps around, so a drifting layer has no seam', () => {
    // The step across the wrap is no bigger than steps inside the texture.
    let inside = 0;
    let across = 0;
    for (let y = 0; y < options.height; y++) {
      inside = Math.max(inside, Math.abs(at(1, y) - at(0, y)));
      across = Math.max(across, Math.abs(at(0, y) - at(options.width - 1, y)));
    }
    expect(across).toBeLessThan(Math.max(inside, 0.05) * 2);
  });

  it('draws the same texture for the same seed', () => {
    expect(tileableNoise(options)).toEqual(noise);
    expect(tileableNoise({ ...options, seed: 6 })).not.toEqual(noise);
  });
});
