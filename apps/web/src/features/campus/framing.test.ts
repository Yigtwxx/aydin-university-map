import { PerspectiveCamera, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import {
  CLUSTER_GAP_M,
  type EnuPoint,
  FILL,
  type FreeView,
  freeView,
  hiddenShare,
  mainCluster,
  type Mass,
  MAX_HIDDEN,
  OVERVIEW,
  type OverviewFrame,
  overviewFrame,
  routeView,
} from './framing';

/** A filled rectangle of points about every `step` metres, edges included. */
const grid = (
  e0: number,
  e1: number,
  n0: number,
  n1: number,
  step = 20,
): EnuPoint[] => {
  const out: EnuPoint[] = [];
  const ce = Math.max(1, Math.ceil((e1 - e0) / step));
  const cn = Math.max(1, Math.ceil((n1 - n0) / step));
  for (let i = 0; i <= ce; i++)
    for (let j = 0; j <= cn; j++)
      out.push([e0 + ((e1 - e0) * i) / ce, n0 + ((n1 - n0) * j) / cn]);
  return out;
};

const extent = (points: readonly EnuPoint[]) => ({
  minE: Math.min(...points.map((p) => p[0])),
  maxE: Math.max(...points.map((p) => p[0])),
  minN: Math.min(...points.map((p) => p[1])),
  maxN: Math.max(...points.map((p) => p[1])),
});

// Shaped like the data: the main campus, T Blok to the south, the aviation
// centre off its south-west corner, and the girls' dormitory ~400 m west
// across the motorway.
const campus = grid(-95, 114, -180, 144);
const tBlock = grid(-38, 61, -293, -188, 10);
const aviation = grid(-142, -124, -223, -196, 6);
const dorm = [...grid(-556, -498, -322, -258, 10), [-557, -282] as EnuPoint];

describe('mainCluster', () => {
  it('drops a far-off site and keeps the campus whole', () => {
    const kept = mainCluster([...dorm, ...campus, ...tBlock, ...aviation]);
    expect(kept).toHaveLength(campus.length + tBlock.length + aviation.length);
    const box = extent(kept);
    expect(box.minE).toBe(-142);
    expect(box.maxE).toBe(114);
    // T Blok stays in.
    expect(box.minN).toBe(-293);
    expect(box.maxN).toBe(144);
    expect(kept.some((p) => p[0] < -400)).toBe(false);
  });

  it('chains points closer than the gap into one cluster', () => {
    const line: EnuPoint[] = Array.from({ length: 10 }, (_, i) => [
      i * (CLUSTER_GAP_M - 1),
      0,
    ]);
    expect(mainCluster([...line, [5000, 0]])).toEqual(line);
  });

  it('splits points just beyond the gap', () => {
    const a: EnuPoint[] = [
      [0, 0],
      [10, 0],
      [20, 0],
    ];
    const b: EnuPoint[] = [
      [20 + CLUSTER_GAP_M + 1, 0],
      [30 + CLUSTER_GAP_M + 1, 0],
    ];
    expect(mainCluster([...b, ...a])).toEqual(a);
  });

  it('works across negative grid cells', () => {
    const pts: EnuPoint[] = [
      [-1, -1],
      [1, 1],
      [-140, 0],
    ];
    expect(mainCluster(pts)).toEqual(pts);
  });

  it('keeps everything when nothing is apart, and nothing from nothing', () => {
    expect(mainCluster(campus)).toEqual(campus);
    expect(mainCluster([])).toEqual([]);
    expect(mainCluster([[3, 4]])).toEqual([[3, 4]]);
  });
});

/** Where the frame's camera shows `points`, in normalised device coordinates. */
const project = (
  points: readonly EnuPoint[],
  frame: OverviewFrame,
  view: FreeView,
) => {
  const camera = new PerspectiveCamera(
    (2 * Math.atan(view.tanV) * 180) / Math.PI,
    view.tanH / view.tanV,
    1,
    10_000,
  );
  const [te, tn] = frame.centre;
  camera.position.set(
    te + frame.distance * OVERVIEW[0],
    frame.distance * OVERVIEW[1],
    -tn + frame.distance * OVERVIEW[2],
  );
  camera.lookAt(te, 0, -tn);
  camera.updateMatrixWorld();
  const ndc = points.map((p) => new Vector3(p[0], 0, -p[1]).project(camera));
  return {
    minX: Math.min(...ndc.map((v) => v.x)),
    maxX: Math.max(...ndc.map((v) => v.x)),
    minY: Math.min(...ndc.map((v) => v.y)),
    maxY: Math.max(...ndc.map((v) => v.y)),
  };
};

describe('freeView', () => {
  it('measures the uncovered part of the canvas', () => {
    const tan = Math.tan((34 * Math.PI) / 360);
    const view = freeView(1440, 900, 384, 0, 34);
    expect(view.tanV).toBeCloseTo(tan, 9);
    expect(view.tanH).toBeCloseTo((tan * 1056) / 900, 9);
    const sheet = freeView(390, 844, 0, 344, 34);
    expect(sheet.tanV).toBeCloseTo((tan * 500) / 844, 9);
  });
});

describe('overviewFrame', () => {
  const desktop = freeView(1440, 900, 384, 0, 34);
  const phone = freeView(390 - 56, 844, 0, 300, 34);
  const site = [...campus, ...tBlock, ...aviation];

  it('fits the campus centred in the free view, FILL of it', () => {
    for (const view of [desktop, phone]) {
      const frame = overviewFrame(site, view, 0);
      const box = project(site, frame, view);
      expect((box.minX + box.maxX) / 2).toBeCloseTo(0, 4);
      expect((box.minY + box.maxY) / 2).toBeCloseTo(0, 4);
      // The tighter direction touches FILL, the other stays inside it.
      const fill = Math.max(
        (box.maxX - box.minX) / 2,
        (box.maxY - box.minY) / 2,
      );
      expect(fill).toBeCloseTo(FILL, 4);
      expect(box.maxX).toBeLessThanOrEqual(FILL + 1e-6);
      expect(box.maxY).toBeLessThanOrEqual(FILL + 1e-6);
    }
  });

  it('keeps T Blok in view and the dormitory out', () => {
    const kept = mainCluster([...dorm, ...site]);
    const frame = overviewFrame(kept, desktop, 260);
    const t = project(tBlock, frame, desktop);
    expect(t.minY).toBeGreaterThanOrEqual(-FILL - 1e-6);
    const d = project(dorm, frame, desktop);
    expect(d.minX).toBeLessThan(-1);
  });

  it('lands on the campus, not between it and the dormitory', () => {
    const { centre } = overviewFrame(
      mainCluster([...dorm, ...site]),
      desktop,
      0,
    );
    expect(centre[0]).toBeGreaterThan(-60);
    expect(centre[0]).toBeLessThan(40);
    expect(centre[1]).toBeGreaterThan(-140);
    expect(centre[1]).toBeLessThan(0);
    const wide = overviewFrame([...dorm, ...site], desktop, 0);
    expect(wide.centre[0]).toBeLessThan(-150);
  });

  it('comes closer for a smaller campus and never under the floor', () => {
    const big = overviewFrame(grid(-300, 300, -300, 300), desktop, 0);
    const small = overviewFrame(grid(-100, 100, -100, 100), desktop, 0);
    expect(small.distance).toBeLessThan(big.distance);
    const spot = overviewFrame([[5, 7]], desktop, 260);
    expect(spot.distance).toBe(260);
    expect(spot.centre[0]).toBeCloseTo(5, 6);
    expect(spot.centre[1]).toBeCloseTo(7, 6);
    expect(overviewFrame([], desktop, 170)).toEqual({
      centre: [0, 0],
      distance: 170,
    });
  });

  it('backs off for a narrower view', () => {
    const points = grid(-150, 150, -150, 150);
    const wide = overviewFrame(points, freeView(1440, 900, 0, 0, 34), 0);
    const narrow = overviewFrame(points, freeView(400, 900, 0, 0, 34), 0);
    expect(narrow.distance).toBeGreaterThan(wide.distance);
  });
});

describe('routeView', () => {
  const view: FreeView = { tanH: 0.6, tanV: 0.4 };
  // A 20 m route running east, 3 m north of a 12 m block: the overview looks
  // from the south-south-east, over the block.
  const route: EnuPoint[] = [
    [0, 13],
    [20, 13],
  ];
  const block: Mass = {
    ring: [
      [-10, -10],
      [30, -10],
      [30, 10],
      [-10, 10],
    ],
    height: 12,
  };

  it('keeps the overview’s own look when nothing hides the route', () => {
    const { direction } = routeView(route, route, view, 60, []);
    expect(direction).toEqual(OVERVIEW);
  });

  it('looks down more steeply at a route behind a tall block', () => {
    const plain = overviewFrame(route, view, 60);
    expect(hiddenShare(route, plain, OVERVIEW, [block])).toBeGreaterThan(
      MAX_HIDDEN,
    );
    const { frame, direction } = routeView(route, route, view, 60, [block]);
    expect(direction[1]).toBeGreaterThan(OVERVIEW[1]);
    // Same bearing: only the pitch changes.
    expect(direction[0] / direction[2]).toBeCloseTo(OVERVIEW[0] / OVERVIEW[2]);
    expect(hiddenShare(route, frame, direction, [block])).toBeLessThanOrEqual(
      MAX_HIDDEN,
    );
  });

  it('looks from the other side at a route hugging a tall block', () => {
    const tower: Mass = { ...block, height: 40 };
    const hugging: EnuPoint[] = [
      [0, 11],
      [20, 11],
    ];
    const { frame, direction } = routeView(hugging, hugging, view, 60, [tower]);
    // Seen from the north: the camera stands north of the route.
    expect(direction[2]).toBeLessThan(0);
    expect(hiddenShare(hugging, frame, direction, [tower])).toBeLessThanOrEqual(
      MAX_HIDDEN,
    );
  });

  it('sees under a raised slab', () => {
    // A strip just south of the route: solid it hides the route; raised on
    // columns 20 m up the eye passes under it.
    const ring: EnuPoint[] = [
      [-10, 9],
      [30, 9],
      [30, 11],
      [-10, 11],
    ];
    const plain = overviewFrame(route, view, 60);
    const solid = hiddenShare(route, plain, OVERVIEW, [{ ring, height: 25 }]);
    const slab = hiddenShare(route, plain, OVERVIEW, [
      { ring, height: 25, base: 20 },
    ]);
    expect(solid).toBeGreaterThan(MAX_HIDDEN);
    expect(slab).toBe(0);
  });
});
