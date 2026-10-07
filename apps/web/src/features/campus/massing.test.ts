import { Color, type BufferGeometry } from 'three';
import { describe, expect, it } from 'vitest';

import { fitStoreys, GROUND_MODE, WINDOW_MODE } from './facadeRecipe';
import { buildMassing, massingRecipes, seedOf, STYLE_INDEX } from './massing';
import type { Building, Facade, FacadeFeature } from './types';

const square = (size: number): [number, number][] => [
  [0, 0],
  [size, 0],
  [size, size],
  [0, size],
  [0, 0],
];

describe('buildMassing', () => {
  it('writes the facade attributes the shader reads', () => {
    const g = buildMassing([
      {
        id: 'way/1',
        name: null,
        campus: false,
        height_m: 15,
        outline: square(20),
        style: 'apartment',
        levels: 5,
        roof: { shape: 'flat' },
      },
    ]);
    expect(g).toBeDefined();
    for (const name of [
      'position',
      'normal',
      'color',
      'aWall',
      'aMeta',
      'aFlags',
      'aRise',
    ])
      expect(g!.getAttribute(name)).toBeDefined();
    const meta = g!.getAttribute('aMeta');
    expect(meta.getX(0)).toBe(STYLE_INDEX.apartment);
    expect(meta.getZ(0)).toBe(5);
  });

  it('puts a hipped roof above the eaves', () => {
    const building: Building = {
      id: 'way/2',
      name: null,
      campus: false,
      height_m: 9,
      outline: square(10),
      style: 'house',
      roof: {
        shape: 'hipped',
        obb: square(10).slice(0, 4),
        rise: 2,
        overhang: 0.4,
      },
    };
    const g = buildMassing([building])!;
    g.computeBoundingBox();
    expect(g.boundingBox!.max.y).toBeCloseTo(11, 5);
  });

  it('builds a mosque with a dome and a minaret taller than the walls', () => {
    const g = buildMassing([
      {
        id: 'way/3',
        name: 'Cami',
        campus: false,
        height_m: 9,
        outline: square(18),
        style: 'worship',
        roof: {
          shape: 'dome',
          centre: [9, 9],
          radius: 7,
          minaret: [0, 0],
          minaret_m: 30,
        },
      },
    ])!;
    g.computeBoundingBox();
    expect(g.boundingBox!.max.y).toBeCloseTo(30, 5);
  });
});

describe('seedOf', () => {
  it('is stable and within 0..1', () => {
    expect(seedOf('way/42')).toBe(seedOf('way/42'));
    expect(seedOf('way/42')).toBeGreaterThanOrEqual(0);
    expect(seedOf('way/42')).toBeLessThan(1);
    expect(seedOf('way/42')).not.toBe(seedOf('way/43'));
  });
});

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

function featureOf(overrides: Partial<FacadeFeature>): FacadeFeature {
  return {
    kind: 'tower',
    at: [10, 10],
    width_m: 3,
    depth_m: 3,
    height_m: 3,
    base_m: 0,
    facing_deg: 0,
    colour: '#ffffff',
    accent: null,
    ...overrides,
  };
}

/** A 20 m square block (not on the campus, so the opening's origin stays put). */
function block(id: string, facade?: Facade, east = 0): Building {
  return {
    id,
    name: null,
    campus: false,
    height_m: 14.2,
    levels: 4,
    style: 'campus',
    outline: square(20).map(([e, n]) => [e + east, n]),
    roof: { shape: 'flat' },
    ...(facade ? { facade } : {}),
  };
}

const count = (g: BufferGeometry | undefined) =>
  g?.getAttribute('position').count ?? 0;

/** Vertices whose (three.js) normal is `normal` and that carry windows. */
function facadeVertices(g: BufferGeometry, normal: [number, number, number]) {
  const n = g.getAttribute('normal');
  const wall = g.getAttribute('aWall');
  const out: number[] = [];
  for (let i = 0; i < n.count; i++)
    if (
      Math.abs(n.getX(i) - normal[0]) < 1e-6 &&
      Math.abs(n.getY(i) - normal[1]) < 1e-6 &&
      Math.abs(n.getZ(i) - normal[2]) < 1e-6 &&
      wall.getW(i) > 0
    )
      out.push(i);
  return out;
}

const SOUTH: [number, number, number] = [0, 0, 1];
const EAST: [number, number, number] = [1, 0, 0];

describe('buildMassing without a facade recipe', () => {
  it('keeps the style look: no recipe in the flags, no recipe texture', () => {
    const g = buildMassing([block('way/10')])!;
    // Four walls and a roof: 4 x 6 + 2 x 3 vertices.
    expect(count(g)).toBe(30);
    const flags = g.getAttribute('aFlags');
    expect(flags.itemSize).toBe(4);
    expect(flags.array).toBeInstanceOf(Uint8Array);
    for (let i = 0; i < flags.count; i++) {
      expect(flags.getY(i)).toBe(0);
      expect(flags.getZ(i)).toBe(0);
      expect(flags.getW(i)).toBe(0);
    }
    expect(massingRecipes(g)).toBeUndefined();
    const meta = g.getAttribute('aMeta');
    expect(meta.getX(0)).toBe(STYLE_INDEX.campus);
    expect(meta.getZ(0)).toBe(4);
  });

  it('is untouched by a recipe block next to it', () => {
    const alone = buildMassing([block('way/10')])!;
    const both = buildMassing([
      block('way/10'),
      block(
        'way/11',
        facadeOf({
          plinth: '#8e3b2f',
          features: [featureOf({ at: [50, 10], height_m: 20 })],
        }),
        40,
      ),
    ])!;
    for (const name of [
      'position',
      'normal',
      'color',
      'aWall',
      'aMeta',
      'aFlags',
      'aRise',
    ]) {
      const a = alone.getAttribute(name).array;
      const b = both.getAttribute(name).array;
      expect(Array.from(b.slice(0, a.length))).toEqual(Array.from(a));
    }
  });
});

describe('buildMassing with a facade recipe', () => {
  const facade = facadeOf({
    wall: '#e9d8a6',
    plinth: '#8e3b2f',
    walls: [
      {
        facing_deg: 160,
        tolerance_deg: 30,
        windows: 'curtain',
        wall: '#ffffff',
        ground: 'glazed',
      },
    ],
  });

  it('marks the walls with their recipe and fitted floors', () => {
    const g = buildMassing([block('way/20', facade)])!;
    const texture = massingRecipes(g)!;
    expect(texture.image.height).toBe(1);
    const flags = g.getAttribute('aFlags');
    const meta = g.getAttribute('aMeta');
    const wall = g.getAttribute('aWall');
    const fit = fitStoreys(facade, 14.2, 4);
    const [east] = facadeVertices(g, EAST);
    expect(flags.getY(east!)).toBe(1);
    expect(flags.getZ(east!)).toBe(WINDOW_MODE.punched);
    expect(flags.getW(east!)).toBe(GROUND_MODE.same);
    expect(meta.getZ(east!)).toBe(fit.upper);
    expect(meta.getW(east!)).toBeCloseTo(fit.ground);
    expect(wall.getW(east!)).toBeCloseTo(fit.storey);
    // The recipe's wall colour, without the style's random variation.
    const cream = new Color('#e9d8a6');
    const color = g.getAttribute('color');
    expect(color.getX(east!)).toBeCloseTo(cream.r, 5);
    expect(color.getY(east!)).toBeCloseTo(cream.g, 5);
  });

  it('gives the side facing the override its glass front and colour', () => {
    const g = buildMassing([block('way/20', facade)])!;
    const flags = g.getAttribute('aFlags');
    const color = g.getAttribute('color');
    const south = facadeVertices(g, SOUTH);
    expect(south).toHaveLength(6);
    for (const i of south) {
      expect(flags.getZ(i)).toBe(WINDOW_MODE.curtain);
      expect(flags.getW(i)).toBe(GROUND_MODE.glazed);
      expect(color.getX(i)).toBeCloseTo(1, 5);
    }
    // The east wall (90°) is outside the override's 160° ± 30°.
    for (const i of facadeVertices(g, EAST))
      expect(flags.getZ(i)).toBe(WINDOW_MODE.punched);
  });

  it('shares one texture row between identical recipes', () => {
    const g = buildMassing([
      block('way/20', facade),
      block('way/21', facade, 40),
      block('way/22', facadeOf({ wall: '#ffffff' }), 80),
    ])!;
    expect(massingRecipes(g)!.image.height).toBe(2);
  });

  it('sinks the block deep enough to hide a tower above its roof', () => {
    const tall = facadeOf({
      features: [featureOf({ at: [10, 10], height_m: 30 })],
    });
    const g = buildMassing([block('way/23', tall)])!;
    const rise = g.getAttribute('aRise');
    for (let i = 0; i < rise.count; i++)
      expect(rise.getY(i)).toBeGreaterThanOrEqual(31);
    g.computeBoundingBox();
    expect(g.boundingBox!.max.y).toBeCloseTo(30);
  });
});
