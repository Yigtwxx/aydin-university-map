import { describe, expect, it } from 'vitest';

import { KEYFRAMES, monotoneCubic, poseAt, stageAt } from './cameraPath';

describe('poseAt', () => {
  it('starts high over the city and ends on the map opening pose', () => {
    expect(poseAt(0).eye[2]).toBeCloseTo(30000, 6);
    const end = poseAt(1);
    // CampusScene INTRO_POSITION [420, 1150, 1500] in three.js = ENU (420, -1500, 1150).
    end.eye.forEach((v, i) => expect(v).toBeCloseTo([420, -1500, 1150][i]!, 6));
    expect(end.target).toEqual([0, 0, 0]);
    expect(end.fov).toBe(34);
  });

  it('descends monotonically and clamps outside 0..1', () => {
    let last = Infinity;
    for (let p = 0; p <= 1; p += 0.02) {
      const altitude = poseAt(p).eye[2];
      expect(altitude).toBeLessThanOrEqual(last + 1e-6);
      last = altitude;
    }
    expect(poseAt(-1)).toEqual(poseAt(0));
    expect(poseAt(2)).toEqual(poseAt(1));
  });

  it('never stops between keyframes (no per-keyframe easing)', () => {
    // Altitude keeps falling at a healthy rate through the middle keyframes.
    for (const frame of KEYFRAMES.slice(1, -1)) {
      const before = poseAt(frame.at - 0.01).eye[2];
      const after = poseAt(frame.at + 0.01).eye[2];
      expect(after / before).toBeLessThan(0.985);
    }
  });
});

describe('monotoneCubic', () => {
  it('passes through its points without overshooting', () => {
    const xs = [0, 1, 2, 3];
    const ys = [10, 4, 3, 0];
    xs.forEach((x, i) =>
      expect(monotoneCubic(xs, ys, x)).toBeCloseTo(ys[i]!, 9),
    );
    for (let x = 0; x <= 3; x += 0.05) {
      const y = monotoneCubic(xs, ys, x);
      expect(y).toBeLessThanOrEqual(10);
      expect(y).toBeGreaterThanOrEqual(0);
    }
  });
});

describe('stageAt', () => {
  it('maps the dive to four captions in order', () => {
    expect([0, 0.3, 0.6, 0.9].map(stageAt)).toEqual([0, 1, 2, 3]);
  });
});
