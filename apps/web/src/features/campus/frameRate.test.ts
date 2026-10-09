import { describe, expect, it } from 'vitest';

import { createFrameRateWatch } from './frameRate';

/** Feeds `seconds` of frames at `fps`; true if the watch declined. */
function run(
  watch: ReturnType<typeof createFrameRateWatch>,
  fps: number,
  seconds: number,
): boolean {
  let declined = false;
  for (let i = 0; i < Math.round(fps * seconds); i++)
    declined = watch.frame(1 / fps) || declined;
  return declined;
}

describe('createFrameRateWatch', () => {
  it('keeps the effects at a smooth frame rate', () => {
    expect(run(createFrameRateWatch(), 60, 10)).toBe(false);
  });

  it('turns them down after 2.5 s of slow drawing', () => {
    const watch = createFrameRateWatch();
    expect(run(watch, 20, 2)).toBe(false);
    expect(run(watch, 20, 1)).toBe(true);
  });

  it('forgives a short hitch among smooth frames', () => {
    const watch = createFrameRateWatch();
    run(watch, 60, 2);
    run(watch, 15, 0.5);
    expect(run(watch, 60, 5)).toBe(false);
  });
});
