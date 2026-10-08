import {
  BoxGeometry,
  PerspectiveCamera,
  Ray,
  Raycaster,
  Vector2,
  Vector3,
} from 'three';
import { MeshBVH } from 'three-mesh-bvh';
import { describe, expect, it } from 'vitest';

import {
  boundsShift,
  clampScale,
  GRAB_MAX_M,
  PAN_MARGIN_M,
  panBounds,
  pickPoint,
  rayAtHeight,
  releaseVelocity,
  wheelScale,
  zoomAbout,
} from './mapGestures';

const down = (x: number, y: number, z: number, dx = 0.3, dz = 0) =>
  new Ray(new Vector3(x, y, z), new Vector3(dx, -1, dz).normalize());

/** A block 20 m tall spanning x, z in [-10, 10], as the massing BVH. */
const block = () => {
  const geometry = new BoxGeometry(20, 20, 20).translate(0, 10, 0);
  return new MeshBVH(geometry);
};

describe('rayAtHeight', () => {
  it('meets the ground ahead of the ray', () => {
    const hit = rayAtHeight(down(0, 100, 0), 0, new Vector3());
    expect(hit?.y).toBeCloseTo(0);
    expect(hit?.x).toBeCloseTo(30);
  });

  it('misses above the horizon and beyond reach', () => {
    const up = new Ray(new Vector3(0, 100, 0), new Vector3(0, 1, 0));
    expect(rayAtHeight(up, 0, new Vector3())).toBeUndefined();
    const grazing = new Ray(
      new Vector3(0, 100, 0),
      new Vector3(1, -0.01, 0).normalize(),
    );
    expect(rayAtHeight(grazing, 0, new Vector3())).toBeUndefined();
    expect(GRAB_MAX_M).toBeLessThan(100 / 0.01);
  });
});

describe('pickPoint', () => {
  it('grabs a roof before the ground behind it', () => {
    const hit = pickPoint(down(0, 100, 0, 0), [block()], new Vector3());
    expect(hit?.y).toBeCloseTo(20);
  });

  it('falls back to the ground past the blocks', () => {
    const hit = pickPoint(down(100, 100, 0, 0), [block()], new Vector3());
    expect(hit?.y).toBeCloseTo(0);
    expect(hit?.x).toBeCloseTo(100);
  });
});

describe('wheelScale', () => {
  it('zooms in on a scroll up and out on a scroll down', () => {
    expect(wheelScale(-100, 0, false)).toBeLessThan(1);
    expect(wheelScale(100, 0, false)).toBeGreaterThan(1);
    expect(wheelScale(100, 0, false) * wheelScale(-100, 0, false)).toBeCloseTo(
      1,
    );
  });

  it('treats a line as 16 px and caps a flick', () => {
    expect(wheelScale(3, 1, false)).toBeCloseTo(wheelScale(48, 0, false));
    expect(wheelScale(5000, 0, false)).toBe(wheelScale(160, 0, false));
  });

  it('gears up the small deltas of a trackpad pinch', () => {
    expect(wheelScale(-10, 0, true)).toBeLessThan(wheelScale(-10, 0, false));
  });
});

describe('zoomAbout', () => {
  const pose = {
    position: new Vector3(0, 300, 300),
    target: new Vector3(0, 0, 0),
  };

  it('keeps the anchor on the same line of sight', () => {
    const anchor = new Vector3(80, 0, -40);
    const next = zoomAbout(pose, anchor, 0.5);
    const before = anchor.clone().sub(pose.position).normalize();
    const after = anchor.clone().sub(next.position).normalize();
    expect(after.distanceTo(before)).toBeCloseTo(0);
    expect(next.position.distanceTo(next.target)).toBeCloseTo(
      pose.position.distanceTo(pose.target) * 0.5,
    );
  });

  it('keeps the target on the ground for a roof anchor', () => {
    const next = zoomAbout(pose, new Vector3(20, 25, 10), 0.5);
    expect(next.target.y).toBeCloseTo(0);
    const view = pose.target.clone().sub(pose.position).normalize();
    const nextView = next.target.clone().sub(next.position).normalize();
    expect(nextView.distanceTo(view)).toBeCloseTo(0);
  });

  it('holds the pixel under the cursor through a zoom', () => {
    const camera = new PerspectiveCamera(34, 1.5, 1, 5000);
    camera.setViewOffset(1200, 800, -150, 60, 1200, 800);
    const look = (p: { position: Vector3; target: Vector3 }) => {
      camera.position.copy(p.position);
      camera.lookAt(p.target);
      camera.updateMatrixWorld();
    };
    look(pose);
    const raycaster = new Raycaster();
    const cursor = new Vector2(0.4, -0.3);
    raycaster.setFromCamera(cursor, camera);
    const anchor = rayAtHeight(raycaster.ray, 0, new Vector3())!;
    look(zoomAbout(pose, anchor, 0.4));
    const seen = anchor.clone().project(camera);
    expect(seen.x).toBeCloseTo(cursor.x);
    expect(seen.y).toBeCloseTo(cursor.y);
  });
});

describe('clampScale', () => {
  it('stops at the nearest and farthest distances', () => {
    expect(clampScale(100, 0.1, 30, 1400)).toBeCloseTo(0.3);
    expect(clampScale(1000, 3, 30, 1400)).toBeCloseTo(1.4);
    expect(clampScale(100, 0.5, 30, 1400)).toBeCloseTo(0.5);
  });
});

describe('panBounds and boundsShift', () => {
  it('boxes the points with a margin in world axes', () => {
    const box = panBounds([
      [0, 0],
      [100, 200],
    ]);
    expect(box.min.x).toBe(-PAN_MARGIN_M);
    expect(box.max.x).toBe(100 + PAN_MARGIN_M);
    // North is -z.
    expect(box.min.z).toBe(-200 - PAN_MARGIN_M);
    expect(box.max.z).toBe(PAN_MARGIN_M);
  });

  it('leaves an empty campus unbounded', () => {
    const box = panBounds([]);
    expect(box.containsPoint(new Vector3(1e6, 0, -1e6))).toBe(true);
  });

  it('shifts a target back inside, horizontally only', () => {
    const box = panBounds([[0, 0]], 100);
    const shift = boundsShift(new Vector3(150, 5, -20), box, new Vector3());
    expect(shift.toArray()).toEqual([-50, 0, 0]);
    expect(
      boundsShift(new Vector3(10, 0, 10), box, new Vector3()).length(),
    ).toBe(0);
  });
});

describe('releaseVelocity', () => {
  const samples = [
    { t: 0, x: 0, z: 0 },
    { t: 40, x: 4, z: 0 },
    { t: 80, x: 8, z: -2 },
  ];

  it('throws at the speed of the last moments', () => {
    const v = releaseVelocity(samples, 90);
    expect(v.x).toBeCloseTo(100);
    expect(v.z).toBeCloseTo(-25);
  });

  it('does not glide after a pause or a single sample', () => {
    expect(releaseVelocity(samples, 300).length()).toBe(0);
    expect(releaseVelocity(samples.slice(0, 1), 5).length()).toBe(0);
  });
});
