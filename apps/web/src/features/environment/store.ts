import { create } from 'zustand';

import type { Condition } from './weather';

/**
 * Preview overrides for the live sky. Live is the default; a visitor can
 * scrub the time of day or try a weather, then return to live.
 */
interface EnvironmentState {
  /** Hours since local midnight (campus time), e.g. 21.5 = 21:30. */
  hour?: number;
  condition?: Condition;
  setHour: (hour?: number) => void;
  setCondition: (condition?: Condition) => void;
  backToLive: () => void;
}

export const useEnvironmentStore = create<EnvironmentState>((set) => ({
  hour: undefined,
  condition: undefined,
  setHour: (hour) => set({ hour }),
  setCondition: (condition) => set({ condition }),
  backToLive: () => set({ hour: undefined, condition: undefined }),
}));

const ISTANBUL_OFFSET_MS = 3 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/** `now` moved to `hour` o'clock of the same campus (UTC+3) day. */
export function atCampusHour(now: Date, hour: number): Date {
  const local = now.getTime() + ISTANBUL_OFFSET_MS;
  const midnight = Math.floor(local / DAY_MS) * DAY_MS;
  return new Date(midnight + hour * 60 * 60 * 1000 - ISTANBUL_OFFSET_MS);
}

/** Campus-time hours of `date` (0 ≤ h < 24). */
export function campusHour(date: Date): number {
  const local = (date.getTime() + ISTANBUL_OFFSET_MS) % DAY_MS;
  return local / (60 * 60 * 1000);
}
