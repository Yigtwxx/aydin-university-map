import { describe, expect, it } from 'vitest';

import {
  coveredHeight,
  cycleSnap,
  lowerSnap,
  PEEK_PX,
  pickSnap,
  raiseSnap,
  rubberBand,
  snapHeights,
} from './sheet';

describe('snapHeights', () => {
  it('uses 140 px, half and 92 % of a phone viewport', () => {
    expect(snapHeights(844)).toEqual({ peek: PEEK_PX, half: 422, full: 776 });
  });

  it('keeps the status row clear and the snaps ordered on short screens', () => {
    const { peek, half, full } = snapHeights(360);
    expect(full).toBe(300);
    expect(peek).toBeLessThan(half);
    expect(half).toBeLessThan(full);
    const tiny = snapHeights(150);
    expect(tiny.peek).toBeLessThan(tiny.half);
    expect(tiny.half).toBeLessThan(tiny.full);
  });

  it('adds the bottom margin to the covered height', () => {
    expect(coveredHeight(140)).toBe(148);
  });
});

describe('pickSnap', () => {
  const heights = snapHeights(844);

  it('settles on the nearest snap when released slowly', () => {
    expect(pickSnap(180, 0, heights)).toBe('peek');
    expect(pickSnap(400, 0, heights)).toBe('half');
    expect(pickSnap(700, 0, heights)).toBe('full');
  });

  it('carries a flick on to the next snap', () => {
    // Just above peek, flicked upwards: half, not back to peek.
    expect(pickSnap(200, 1400, heights)).toBe('half');
    // Just below full, flicked downwards: half.
    expect(pickSnap(740, -1800, heights)).toBe('half');
    // A hard flick from half goes all the way down.
    expect(pickSnap(422, -2500, heights)).toBe('peek');
  });
});

describe('rubberBand', () => {
  it('follows the finger between the limits and resists past them', () => {
    expect(rubberBand(300, 140, 776)).toBe(300);
    expect(rubberBand(876, 140, 776)).toBeCloseTo(776 + 18);
    expect(rubberBand(40, 140, 776)).toBeCloseTo(140 - 18);
  });
});

describe('snap steps', () => {
  it('cycles with the handle and steps with the keys', () => {
    expect(cycleSnap('peek')).toBe('half');
    expect(cycleSnap('half')).toBe('full');
    expect(cycleSnap('full')).toBe('peek');
    expect(raiseSnap('full')).toBe('full');
    expect(raiseSnap('peek')).toBe('half');
    expect(lowerSnap('full')).toBe('half');
    expect(lowerSnap('peek')).toBe('peek');
  });
});
