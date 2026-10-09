/** Drawing time per measurement (s). */
const WINDOW_S = 0.25;
/** Measurements weighed together: 2.5 s of drawing. */
const WINDOWS = 10;
/** Below this the effects cost more than the machine has. */
const SLOW_FPS = 40;
/** Slow measurements among the last `WINDOWS` that turn the effects down. */
const SLOW_WINDOWS = 8;

export interface FrameRateWatch {
  /**
   * One drawn frame `delta` seconds after the previous one, with no pause
   * between them; true once drawing has been slow for long enough.
   */
  frame(delta: number): boolean;
}

/**
 * The frame rate of the drawing itself. The map draws on demand, so its
 * frames come in runs (a drag, a route's pulse, falling rain) with idle
 * pauses between them; the caller leaves out the first frame after a pause,
 * whose delta is idle time, not drawing time. (drei's PerformanceMonitor
 * counts the pauses and would turn the effects down on any machine.)
 */
export function createFrameRateWatch(): FrameRateWatch {
  let time = 0;
  let frames = 0;
  const rates: number[] = [];
  return {
    frame(delta) {
      time += delta;
      frames += 1;
      if (time < WINDOW_S) return false;
      rates.push(frames / time);
      if (rates.length > WINDOWS) rates.shift();
      time = 0;
      frames = 0;
      return (
        rates.length === WINDOWS &&
        rates.filter((rate) => rate < SLOW_FPS).length >= SLOW_WINDOWS
      );
    },
  };
}
