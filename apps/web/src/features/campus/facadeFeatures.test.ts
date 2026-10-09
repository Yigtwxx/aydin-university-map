import { type BufferGeometry, Color, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { MASONRY_MODE } from './facadeRecipe';
import {
  buildFeatures,
  featuresTop,
  offsetRing,
  planAngle,
} from './facadeFeatures';
import { Builder, type BuildingMeta } from './massing';
import type { Facade, FacadeFeature } from './types';

const META: BuildingMeta = {
  style: 0,
  seed: 0.5,
  storeys: 3,
  storey: 3.4,
  ground: 4,
  shops: 0,
  rise: 1.25,
  sink: 40,
  recipe: 1,
  windows: 2,
  groundFloor: 1,
};

/** Counter-clockwise 20 m square, open. */
const RING: [number, number][] = [
  [0, 0],
  [20, 0],
  [20, 20],
  [0, 20],
];

function facadeWith(features: FacadeFeature[]): Facade {
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
    features,
  };
}

function featureOf(overrides: Partial<FacadeFeature>): FacadeFeature {
  return {
    kind: 'tower',
    at: [10, 10],
    width_m: 4,
    depth_m: 2,
    height_m: 6,
    base_m: 0,
    facing_deg: 0,
    colour: '#8e3b2f',
    accent: null,
    ...overrides,
  };
}

function build(...features: FacadeFeature[]): BufferGeometry | undefined {
  const builder = new Builder();
  buildFeatures(builder, RING, facadeWith(features), META);
  return builder.build();
}

const count = (g: BufferGeometry | undefined) =>
  g?.getAttribute('position').count ?? 0;

/** Box: 4 walls of 6 vertices, a top of 2 triangles. */
const BOX = 4 * 6 + 2 * 3;
/** Drum ring of 32 segments: 6 vertices each; a 32-gon cap is 30 triangles. */
const DRUM_SIDE = 32 * 6;
const DRUM_CAP = 30 * 3;

describe('buildFeatures', () => {
  it('builds a tower as a box, plus a coping with an accent', () => {
    expect(count(build(featureOf({ kind: 'tower' })))).toBe(BOX);
    expect(count(build(featureOf({ kind: 'tower', accent: '#ffffff' })))).toBe(
      BOX + BOX + 6,
    );
  });

  it('builds a glass box, framed when it has an accent', () => {
    expect(count(build(featureOf({ kind: 'glass' })))).toBe(BOX);
    expect(count(build(featureOf({ kind: 'glass', accent: '#ffffff' })))).toBe(
      BOX * 3,
    );
  });

  it('stands a raised glass walk on a parapet, between glazing bars', () => {
    const bridge = featureOf({
      kind: 'glass',
      base_m: 4.8,
      height_m: 3,
      depth_m: 16,
      accent: '#f2f2f0',
    });
    // Glass, parapet (with its underside), roof slab and 11 bars a side.
    expect(count(build(bridge))).toBe(BOX * 3 + 6 + BOX * 22);
    // A raised vestibule under 3 m keeps its thin frame.
    const vestibule = featureOf({ kind: 'glass', base_m: 1.7, accent: '#fff' });
    expect(count(build(vestibule))).toBe(BOX * 3 + 6);
  });

  it('keeps a framed glass box free of coplanar caps in two colours', () => {
    // A bridge walk: its glass top and its frame's roof in one plane flicker.
    const g = build(
      featureOf({
        kind: 'glass',
        base_m: 4.8,
        height_m: 3,
        colour: '#9fb7c2',
        accent: '#f2f2f0',
      }),
    )!;
    const position = g.getAttribute('position');
    const normal = g.getAttribute('normal');
    const color = g.getAttribute('color');
    const colours = new Map<string, Set<string>>();
    for (let i = 0; i < position.count; i++) {
      if (Math.abs(normal.getY(i)) < 0.99) continue;
      const plane = `${Math.sign(normal.getY(i))}@${position.getY(i).toFixed(3)}`;
      const rgb = [color.getX(i), color.getY(i), color.getZ(i)]
        .map((c) => c.toFixed(3))
        .join(',');
      colours.set(plane, (colours.get(plane) ?? new Set()).add(rgb));
    }
    for (const [plane, set] of colours) expect(set.size, plane).toBe(1);
  });

  it('builds a drum with a lip, and an accent stripe', () => {
    const lip = DRUM_SIDE + 2 * DRUM_CAP;
    expect(count(build(featureOf({ kind: 'drum' })))).toBe(DRUM_SIDE + lip);
    expect(count(build(featureOf({ kind: 'drum', accent: '#1d4fa0' })))).toBe(
      3 * DRUM_SIDE + lip,
    );
  });

  it('builds a canopy slab closed underneath', () => {
    expect(count(build(featureOf({ kind: 'canopy' })))).toBe(BOX + 6);
    expect(count(build(featureOf({ kind: 'canopy', accent: '#ffffff' })))).toBe(
      2 * (BOX + 6),
    );
  });

  it('builds a portal from two jambs, a lintel and a door', () => {
    expect(count(build(featureOf({ kind: 'portal' })))).toBe(
      BOX * 3 + (BOX + 6),
    );
  });

  it('wraps a band round the block, capped above (and below off the ground)', () => {
    // 4 walls; a square annulus triangulates into 8 triangles.
    const walls = 4 * 6;
    const annulus = 8 * 3;
    expect(count(build(featureOf({ kind: 'band', at: null })))).toBe(
      walls + annulus,
    );
    expect(count(build(featureOf({ kind: 'band', at: null, base_m: 8 })))).toBe(
      walls + 2 * annulus,
    );
  });

  it('skips a feature with nowhere to stand', () => {
    expect(build(featureOf({ kind: 'tower', at: null }))).toBeUndefined();
  });

  it('turns a feature to face its compass bearing', () => {
    // 4 m across the front, 2 m deep, facing east: 2 m east-west, 4 m north-south.
    const g = build(featureOf({ kind: 'tower', facing_deg: 90 }))!;
    g.computeBoundingBox();
    const size = g.boundingBox!.getSize(new Vector3());
    expect(size.x).toBeCloseTo(2);
    expect(size.z).toBeCloseTo(4);
    expect(size.y).toBeCloseTo(6);
  });

  it("lays a tower in masonry on its block's recipe row", () => {
    const g = build(featureOf({ kind: 'tower', base_m: 14, height_m: 4 }))!;
    const wall = g.getAttribute('aWall');
    const meta = g.getAttribute('aMeta');
    const flags = g.getAttribute('aFlags');
    const walls = [...Array(wall.count).keys()].filter((i) => wall.getW(i) > 0);
    expect(walls).toHaveLength(4 * 6);
    for (const i of walls) {
      expect(flags.getY(i)).toBe(META.recipe);
      expect(flags.getZ(i)).toBe(MASONRY_MODE);
      expect(wall.getW(i)).toBe(4);
      expect(meta.getW(i)).toBe(14);
    }
  });

  it('draws plain shapes that rise with their block', () => {
    const g = build(featureOf({ kind: 'drum', accent: '#1d4fa0' }))!;
    const wall = g.getAttribute('aWall');
    const flags = g.getAttribute('aFlags');
    const rise = g.getAttribute('aRise');
    for (let i = 0; i < wall.count; i++) {
      expect(wall.getW(i)).toBe(0);
      expect(flags.getY(i)).toBe(0);
      expect(rise.getX(i)).toBeCloseTo(META.rise);
      expect(rise.getY(i)).toBe(META.sink);
    }
  });

  it('paints the drum stripe in the accent colour', () => {
    const g = build(
      featureOf({ kind: 'drum', colour: '#ffffff', accent: '#1d4fa0' }),
    )!;
    const blue = new Color('#1d4fa0');
    const color = g.getAttribute('color');
    let striped = 0;
    for (let i = 0; i < color.count; i++)
      if (Math.abs(color.getZ(i) - blue.b) < 1e-5) striped++;
    expect(striped).toBe(DRUM_SIDE);
  });
});

describe('featuresTop', () => {
  it('is the highest feature plus room for its crown', () => {
    const facade = facadeWith([
      featureOf({ height_m: 6 }),
      featureOf({ kind: 'drum', base_m: 10, height_m: 8 }),
    ]);
    expect(featuresTop(facade)).toBeGreaterThanOrEqual(18.25);
    expect(featuresTop(facadeWith([]))).toBe(0);
  });
});

describe('planAngle', () => {
  it('turns local +y (the front) towards the bearing', () => {
    for (const bearing of [0, 90, 160, 270]) {
      const a = planAngle(bearing);
      const front = [-Math.sin(a), Math.cos(a)];
      const rad = (bearing * Math.PI) / 180;
      expect(front[0]).toBeCloseTo(Math.sin(rad));
      expect(front[1]).toBeCloseTo(Math.cos(rad));
    }
  });
});

describe('offsetRing', () => {
  it('moves every corner outwards along the mitre', () => {
    const out = offsetRing(RING, 0.5);
    expect(out[0]![0]).toBeCloseTo(-0.5);
    expect(out[0]![1]).toBeCloseTo(-0.5);
    expect(out[2]![0]).toBeCloseTo(20.5);
    expect(out[2]![1]).toBeCloseTo(20.5);
  });
});
