import { Box3, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { EMPTY_FURNITURE, type Furniture, type Stairs } from './furniture';
import {
  COPING,
  flightGaps,
  flightRail,
  furnitureInstances,
  itemGeometry,
  itemMatrix,
  masonryGeometry,
  RAIL,
  railingGeometry,
  seatingLayout,
  stairTreads,
} from './furnitureGeometry';
import { pointInRing, createTerrain, distanceToRing } from './terrain';

const flight: Stairs = {
  id: 'flight',
  foot: [-4, 10],
  top: [0, 10],
  width_m: 3,
  steps: 10,
  base_z: 0,
  rise_m: 1.5,
  railings: 'both',
};

const furniture = (extra: Partial<Furniture>): Furniture => ({
  ...EMPTY_FURNITURE,
  ...extra,
});

/** Distinct heights of the up-facing faces of a geometry, rounded to mm. */
function upFacing(furnitureData: Furniture) {
  const terrain = createTerrain(furnitureData);
  const geometry = masonryGeometry(furnitureData, terrain)!;
  const position = geometry.getAttribute('position');
  const normal = geometry.getAttribute('normal');
  let triangles = 0;
  const heights = new Set<number>();
  for (let i = 0; i < position.count; i += 3) {
    if (normal.getY(i) < 0.99) continue;
    triangles++;
    heights.add(Math.round(position.getY(i) * 1000) / 1000);
  }
  return { geometry, triangles, heights: [...heights].sort((a, b) => a - b) };
}

describe('stairs', () => {
  const terrain = createTerrain(furniture({ stairs: [flight] }));
  const f = terrain.flights[0]!;

  it('cuts a flight into equal risers and goings', () => {
    const { riser, going, treads } = stairTreads(f, flight.steps);
    expect(treads).toHaveLength(10);
    expect(riser).toBeCloseTo(0.15);
    expect(going).toBeCloseTo(0.4);
    treads.forEach((t, i) => {
      expect(t.top).toBeCloseTo((i + 1) * 0.15);
      expect(t.to - t.from).toBeCloseTo(0.4);
    });
    expect(treads[9]!.top).toBeCloseTo(flight.rise_m);
  });

  it('draws one tread per step, a riser higher each time', () => {
    const { triangles, heights, geometry } = upFacing(
      furniture({ stairs: [flight] }),
    );
    // Each tread: a nosing band and the rest, two triangles each.
    expect(triangles).toBe(10 * 4);
    expect(heights).toHaveLength(10);
    heights.forEach((h, i) => expect(h).toBeCloseTo((i + 1) * 0.15));
    geometry.computeBoundingBox();
    expect(geometry.boundingBox!.max.y).toBeCloseTo(1.5);
  });

  it('puts handrail posts on the treads, the rail a fixed height over the nosings', () => {
    const { posts, rail } = flightRail(f, flight.steps);
    // Run 4 m: 3.7 m between the first and last tread posts needs four
    // spans of at most 1.2 m (five posts), plus one post on each extension.
    expect(posts).toHaveLength(5 + 2);
    const inner = posts.slice(1, -1);
    for (let i = 1; i < inner.length; i++)
      expect(inner[i]!.along - inner[i - 1]!.along).toBeLessThanOrEqual(
        RAIL.postSpacing,
      );
    const { riser, going } = stairTreads(f, flight.steps);
    for (const post of posts.slice(1, -1)) {
      const step = Math.min(10, Math.floor(post.along / going) + 1);
      expect(post.bottom).toBeCloseTo(step * riser);
      // Through the nosings, level past the last one.
      const k = Math.min(post.along, 9 * going);
      const nosingLine = riser + (k * (1.5 - riser)) / (9 * going);
      expect(post.top - nosingLine).toBeCloseTo(RAIL.height);
    }
    expect(posts[0]!.bottom).toBe(0);
    expect(posts[posts.length - 1]!.bottom).toBeCloseTo(1.5);
    // Level extensions past both ends.
    expect(rail[0]![0]).toBeCloseTo(-RAIL.extension);
    expect(rail[0]![1]).toBeCloseTo(rail[1]![1]);
    expect(rail[rail.length - 1]![1]).toBeCloseTo(1.5 + RAIL.height);
  });

  it('rails only the sides asked for', () => {
    const width = (railings: Stairs['railings']) => {
      const data = furniture({ stairs: [{ ...flight, railings }] });
      const geometry = railingGeometry(data, createTerrain(data));
      if (!geometry) return 0;
      geometry.computeBoundingBox();
      // The flight runs east, so its sides are north and south (world z).
      const box = geometry.boundingBox!;
      return box.max.z - box.min.z;
    };
    expect(width('none')).toBe(0);
    expect(width('left')).toBeLessThan(0.1);
    expect(width('both')).toBeCloseTo(3 - 2 * RAIL.inset + RAIL.bar, 2);
  });
});

describe('terraces', () => {
  const outline: [number, number][] = [
    [0, 0],
    [30, 0],
    [30, 30],
    [0, 30],
  ];

  it('raises the paving with a coping on its retaining wall', () => {
    const { heights } = upFacing(
      furniture({
        terraces: [{ id: 'square', outline, z_m: 1.5, edge: 'wall' }],
      }),
    );
    expect(heights).toEqual([1.5, 1.5 + COPING.height]);
  });

  it('opens the coping where a flight arrives at the terrace', () => {
    const terrain = createTerrain(furniture({ stairs: [flight] }));
    // The west edge, walked north to south as the ring runs.
    const gaps = flightGaps([0, 30], [0, 0], 1.5, terrain.flights);
    expect(gaps).toHaveLength(1);
    const [lo, hi] = gaps[0]!;
    // 1.6 m each side of north = 10, i.e. 20 ± 1.55 m from the edge's start.
    expect(lo * 30).toBeCloseTo(20 - 1.55, 1);
    expect(hi * 30).toBeCloseTo(20 + 1.55, 1);
    // A flight arriving at another level leaves the edge alone.
    expect(flightGaps([0, 30], [0, 0], 2.8, terrain.flights)).toEqual([]);
  });

  it('draws a slope edge as a bank reaching out from the outline', () => {
    const data = furniture({
      terraces: [{ id: 'lawn', outline, z_m: 1, edge: 'slope' }],
    });
    const { geometry } = upFacing(data);
    geometry.computeBoundingBox();
    const bank = createTerrain(data).terraces[0]!.bank;
    expect(geometry.boundingBox!.min.x).toBeCloseTo(-bank);
  });
});

describe('seatingLayout', () => {
  const group = {
    id: 'cafe',
    outline: [
      [0, 0],
      [12, 0],
      [12, 8],
      [0, 8],
    ] as [number, number][],
    tables: 8,
    seats_per_table: 4,
    umbrellas: true,
    poi: 'starbucks',
    base_z: 0,
  };

  it('places every table, its chairs and umbrellas inside the area', () => {
    const layout = seatingLayout(group);
    expect(layout.tables).toHaveLength(8);
    expect(layout.chairs).toHaveLength(32);
    expect(layout.umbrellas).toHaveLength(8);
    for (const { at } of layout.tables) {
      expect(pointInRing(at[0], at[1], group.outline)).toBe(true);
      expect(distanceToRing(at[0], at[1], group.outline)).toBeGreaterThan(0.5);
    }
    for (const { at } of layout.chairs)
      expect(pointInRing(at[0], at[1], group.outline)).toBe(true);
  });

  it('spreads tables out and keeps them apart', () => {
    const { tables, pitch } = seatingLayout(group);
    expect(pitch).toBeGreaterThanOrEqual(1.75);
    for (let i = 0; i < tables.length; i++)
      for (let j = i + 1; j < tables.length; j++) {
        const [a, b] = [tables[i]!.at, tables[j]!.at];
        expect(Math.hypot(a[0] - b[0], a[1] - b[1])).toBeGreaterThan(1.7);
      }
  });

  it('turns every chair towards its table', () => {
    const { tables, chairs } = seatingLayout({ ...group, tables: 1 });
    const [te, tn] = tables[0]!.at;
    for (const chair of chairs) {
      const rad = (chair.heading * Math.PI) / 180;
      const toTable = Math.atan2(te - chair.at[0], tn - chair.at[1]);
      const diff = Math.abs(
        ((rad - toTable + 3 * Math.PI) % (2 * Math.PI)) - Math.PI,
      );
      expect(diff).toBeLessThan(0.25);
    }
  });

  it('places what fits in a small area, without umbrellas when it has none', () => {
    const layout = seatingLayout({
      ...group,
      outline: [
        [0, 0],
        [3, 0],
        [3, 3],
        [0, 3],
      ],
      tables: 6,
      umbrellas: false,
    });
    expect(layout.tables.length).toBeGreaterThanOrEqual(1);
    expect(layout.tables.length).toBeLessThan(6);
    expect(layout.umbrellas).toHaveLength(0);
  });
});

describe('furnitureInstances', () => {
  const data = furniture({
    terraces: [
      {
        id: 'square',
        outline: [
          [0, 0],
          [30, 0],
          [30, 30],
          [0, 30],
        ],
        z_m: 1.5,
        edge: 'wall',
      },
    ],
    items: [
      {
        id: 'bench-1',
        kind: 'bench',
        at: [10, 10],
        heading_deg: 90,
        length_m: null,
        base_z: 0,
      },
      {
        id: 'lamp-1',
        kind: 'lamp',
        at: [40, 10],
        heading_deg: 0,
        length_m: null,
        base_z: 0,
      },
      {
        id: 'rack-1',
        kind: 'bike_rack',
        at: [5, 5],
        heading_deg: 0,
        length_m: 3,
        base_z: 0,
      },
    ],
  });
  const instances = furnitureInstances(data, createTerrain(data));
  const position = (kind: Parameters<typeof instances.get>[0], i = 0) =>
    new Vector3().setFromMatrixPosition(instances.get(kind)![i]!);

  it('stands items on the terrace they are on', () => {
    expect(position('bench').y).toBeCloseTo(1.5);
    expect(position('lamp').y).toBe(0);
  });

  it('splits a lamp into its post and its lens, a bike rack into hoops', () => {
    expect(instances.get('lamp')).toHaveLength(1);
    expect(instances.get('lens')).toHaveLength(1);
    expect(instances.get('hoop')).toHaveLength(4);
    const xs = instances
      .get('hoop')!
      .map((m) => new Vector3().setFromMatrixPosition(m).x.toFixed(3));
    expect(new Set(xs).size).toBe(4);
  });

  it('stretches a bench to its default length across its heading', () => {
    // Facing east, its length runs north–south (world z).
    const box = new Box3().setFromBufferAttribute(
      itemGeometry('bench').getAttribute('position') as never,
    );
    box.applyMatrix4(instances.get('bench')![0]!);
    expect(box.max.z - box.min.z).toBeCloseTo(1.8, 1);
    expect(box.max.x - box.min.x).toBeLessThan(0.6);
  });
});

describe('itemMatrix', () => {
  it('turns an item’s front (+z) to its compass heading', () => {
    const front = (heading: number) =>
      new Vector3(0, 0, 1)
        .transformDirection(itemMatrix([0, 0], 0, heading))
        .toArray()
        .map((v) => Math.round(v * 1000) / 1000 + 0);
    expect(front(0)).toEqual([0, 0, -1]); // north is world -z
    expect(front(90)).toEqual([1, 0, 0]); // east
    expect(front(180)).toEqual([0, 0, 1]);
  });
});

describe('masts, cabins and boards', () => {
  const data = furniture({
    items: [
      {
        id: 'flag-1',
        kind: 'flagpole',
        at: [0, 0],
        heading_deg: 0,
        length_m: 12,
        base_z: 0,
      },
      {
        id: 'booth-1',
        kind: 'booth',
        at: [5, 0],
        heading_deg: 0,
        length_m: null,
        base_z: 0,
      },
      {
        id: 'kiosk-1',
        kind: 'kiosk',
        at: [15, 0],
        heading_deg: 0,
        length_m: null,
        base_z: 0,
      },
      {
        id: 'emblem-1',
        kind: 'emblem',
        at: [20, 0],
        heading_deg: 0,
        length_m: 4,
        base_z: 0,
      },
      {
        id: 'letters-1',
        kind: 'letters',
        at: [25, 0],
        heading_deg: 0,
        length_m: null,
        base_z: 0,
      },
      {
        id: 'sign-1',
        kind: 'sign',
        at: [10, 0],
        heading_deg: 0,
        length_m: null,
        base_z: 0,
      },
    ],
  });
  const instances = furnitureInstances(data, createTerrain(data));
  const height = (
    kind: 'flagpole' | 'booth' | 'kiosk' | 'sign' | 'emblem' | 'letters',
  ) => {
    const box = new Box3().setFromBufferAttribute(
      itemGeometry(kind).getAttribute('position') as never,
    );
    box.applyMatrix4(instances.get(kind)![0]!);
    return box.max.y - box.min.y;
  };

  it('scales the seal to its diameter and keeps the letters 1.75 m tall', () => {
    expect(height('emblem')).toBeGreaterThan(0.9);
    expect(height('emblem')).toBeLessThan(1.6);
    expect(height('letters')).toBeCloseTo(1.75, 1);
  });

  it('raises a mast to its length', () => {
    expect(height('flagpole')).toBeCloseTo(12, 1);
  });

  it('draws a cabin and a board at human scale', () => {
    expect(height('booth')).toBeGreaterThan(2.2);
    expect(height('booth')).toBeLessThan(2.6);
    expect(height('kiosk')).toBeGreaterThan(2.1);
    expect(height('kiosk')).toBeLessThan(2.4);
    expect(height('sign')).toBeGreaterThan(1.8);
    expect(height('sign')).toBeLessThan(2.2);
  });
});
