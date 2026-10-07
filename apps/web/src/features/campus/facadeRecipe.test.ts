import { Color, FloatType, RGBAFormat } from 'three';
import { describe, expect, it } from 'vitest';

import {
  angularDistance,
  facingOf,
  fitStoreys,
  MAX_RECIPES,
  packRecipe,
  RECIPE_TEXELS,
  RecipeTable,
  sideOf,
  sillShare,
} from './facadeRecipe';
import type { Facade } from './types';

/** A recipe as the pipeline publishes it: every default filled in. */
function facadeOf(overrides: Partial<Facade> = {}): Facade {
  return {
    wall: '#e9d8a6',
    plinth: null,
    trim: '#f4f1ea',
    glass: '#3b4f5e',
    roof: null,
    windows: 'punched',
    bay_m: 3.4,
    window_width: 0.45,
    window_height: 0.5,
    storey_m: 3.4,
    ground: 'same',
    ground_m: 4.0,
    walls: [],
    features: [],
    ...overrides,
  };
}

describe('packRecipe', () => {
  it('packs rhythm and linear colours into four texels', () => {
    const row = packRecipe(
      facadeOf({ plinth: '#8e3b2f', trim: '#ffffff', bay_m: 2.8 }),
    );
    expect(row).toHaveLength(RECIPE_TEXELS * 4);
    expect(row[0]).toBeCloseTo(2.8);
    expect(row[1]).toBeCloseTo(0.45);
    expect(row[2]).toBeCloseTo(0.5);
    expect(row[3]).toBeCloseTo(sillShare(0.5));
    const brick = new Color('#8e3b2f');
    expect([row[4], row[5], row[6]]).toEqual([
      expect.closeTo(brick.r, 5),
      expect.closeTo(brick.g, 5),
      expect.closeTo(brick.b, 5),
    ]);
    expect(row[7]).toBe(1);
    expect([row[8], row[9], row[10]]).toEqual([1, 1, 1]);
  });

  it('marks a block without a plinth', () => {
    expect(packRecipe(facadeOf())[7]).toBe(0);
  });

  it('keeps the window inside its storey', () => {
    for (const h of [0.2, 0.5, 0.9, 1.0]) {
      expect(sillShare(h)).toBeGreaterThan(0);
      expect(sillShare(h) + h).toBeLessThanOrEqual(1.05);
    }
  });
});

describe('RecipeTable', () => {
  it('gives identical recipes one slot and new ones the next', () => {
    const table = new RecipeTable();
    expect(table.slot(facadeOf())).toBe(1);
    expect(table.slot(facadeOf())).toBe(1);
    expect(table.slot(facadeOf({ wall: '#ffffff', bay_m: 2 }))).toBe(2);
    expect(table.size).toBe(2);
    const data = table.pack();
    expect(data).toHaveLength(2 * RECIPE_TEXELS * 4);
    // Row-major: the second recipe starts one row in.
    expect(data[RECIPE_TEXELS * 4]).toBeCloseTo(2);
  });

  it('builds a float texture, one recipe per row', () => {
    const table = new RecipeTable();
    expect(table.texture()).toBeUndefined();
    table.slot(facadeOf());
    table.slot(facadeOf({ bay_m: 5 }));
    const texture = table.texture()!;
    expect(texture.image.width).toBe(RECIPE_TEXELS);
    expect(texture.image.height).toBe(2);
    expect(texture.type).toBe(FloatType);
    expect(texture.format).toBe(RGBAFormat);
  });

  it('returns slot 0 once full, so the block keeps its style', () => {
    const table = new RecipeTable();
    for (let i = 0; i < MAX_RECIPES; i++)
      expect(table.slot(facadeOf({ bay_m: 1 + i * 0.01 }))).toBe(i + 1);
    expect(table.slot(facadeOf({ bay_m: 11.9 }))).toBe(0);
    // Known recipes still resolve.
    expect(table.slot(facadeOf({ bay_m: 1 }))).toBe(1);
  });
});

describe('facingOf', () => {
  // Counter-clockwise square: south, east, north, west walls.
  const ring: [number, number][] = [
    [0, 0],
    [10, 0],
    [10, 10],
    [0, 10],
  ];
  it('gives the compass direction each wall faces', () => {
    const facings = ring.map((a, i) => facingOf(a, ring[(i + 1) % 4]!));
    expect(facings).toEqual([180, 90, 0, 270]);
  });
});

describe('angularDistance', () => {
  it('wraps round north', () => {
    expect(angularDistance(350, 10)).toBeCloseTo(20);
    expect(angularDistance(10, 350)).toBeCloseTo(20);
    expect(angularDistance(0, 180)).toBeCloseTo(180);
    expect(angularDistance(90, 90)).toBe(0);
  });
});

describe('sideOf', () => {
  const facade = facadeOf({
    walls: [
      {
        facing_deg: 160,
        tolerance_deg: 30,
        windows: 'curtain',
        wall: '#ffffff',
        ground: null,
      },
      {
        facing_deg: 200,
        tolerance_deg: 30,
        windows: 'blank',
        wall: null,
        ground: null,
      },
      {
        facing_deg: 0,
        tolerance_deg: 15,
        windows: null,
        wall: null,
        ground: 'glazed',
      },
    ],
  });

  it('picks the closest override within its tolerance', () => {
    expect(sideOf(facade, 165)?.windows).toBe('curtain');
    expect(sideOf(facade, 195)?.windows).toBe('blank');
    expect(sideOf(facade, 352)?.ground).toBe('glazed');
  });

  it('leaves walls outside every tolerance to the recipe', () => {
    expect(sideOf(facade, 90)).toBeUndefined();
    expect(sideOf(facade, 20)).toBeUndefined();
  });
});

describe('fitStoreys', () => {
  it('fits OSM levels above the surveyed ground floor', () => {
    const fit = fitStoreys(facadeOf(), 14.2, 4);
    expect(fit.ground).toBeCloseTo(4);
    expect(fit.upper).toBe(3);
    expect(fit.storey).toBeCloseTo(3.4);
  });

  it('stretches storeys so the roof never cuts a window', () => {
    const fit = fitStoreys(facadeOf({ storey_m: 3.4 }), 15, undefined);
    expect(fit.upper).toBe(3);
    expect(fit.ground + fit.upper * fit.storey).toBeCloseTo(15);
  });

  it('never squeezes a storey under 2.4 m', () => {
    const fit = fitStoreys(facadeOf(), 10, 6);
    expect(fit.storey).toBeGreaterThanOrEqual(2.4);
    expect(fit.ground + fit.upper * fit.storey).toBeLessThanOrEqual(10.001);
  });

  it('keeps a low kiosk to its ground floor', () => {
    const fit = fitStoreys(facadeOf(), 3, 1);
    expect(fit.ground).toBe(3);
    expect(fit.upper).toBe(0);
  });
});
