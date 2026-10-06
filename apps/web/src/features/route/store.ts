import { create } from 'zustand';

export interface PlaceRef {
  id: string;
  name: string;
}

/** The panel's tabs; `?panel=assistant` opens the second one. */
export type PanelTab = 'directions' | 'assistant';

export interface RouteState {
  from?: PlaceRef;
  to?: PlaceRef;
  avoidStairs: boolean;
  /** Index into the route's steps; drives the camera and the 360° inset. */
  activeStep?: number;
  /** A 360° spot opened from the map without following a route. */
  exploreNodeId?: string;
  panel: PanelTab;
  /**
   * A shared link named a place the map no longer has; it was dropped and
   * the panel says so until the visitor picks or dismisses.
   */
  linkNotice?: 'missingPlace';
  setFrom: (place?: PlaceRef) => void;
  setTo: (place?: PlaceRef) => void;
  swap: () => void;
  setAvoidStairs: (value: boolean) => void;
  setActiveStep: (index?: number) => void;
  setExploreNode: (nodeId?: string) => void;
  setPanel: (panel: PanelTab) => void;
  dismissLinkNotice: () => void;
  /** Replaces the whole route at once (a shared link, back/forward). */
  restore: (route: {
    from?: PlaceRef;
    to?: PlaceRef;
    avoidStairs: boolean;
    activeStep?: number;
    panel?: PanelTab;
    linkNotice?: 'missingPlace';
  }) => void;
  /** Renames the route ends (e.g. after a language switch), keeping the step. */
  relabel: (names: { from?: string; to?: string }) => void;
}

export const useRouteStore = create<RouteState>((set) => ({
  from: undefined,
  to: undefined,
  avoidStairs: false,
  activeStep: undefined,
  exploreNodeId: undefined,
  panel: 'directions',
  linkNotice: undefined,
  setFrom: (from) =>
    set({ from, activeStep: undefined, linkNotice: undefined }),
  setTo: (to) =>
    set({
      to,
      activeStep: undefined,
      exploreNodeId: undefined,
      linkNotice: undefined,
    }),
  swap: () => set((s) => ({ from: s.to, to: s.from, activeStep: undefined })),
  setAvoidStairs: (avoidStairs) => set({ avoidStairs, activeStep: undefined }),
  setActiveStep: (activeStep) =>
    set(
      activeStep === undefined
        ? { activeStep }
        : { activeStep, exploreNodeId: undefined },
    ),
  setExploreNode: (exploreNodeId) =>
    set(
      exploreNodeId === undefined
        ? { exploreNodeId }
        : { exploreNodeId, activeStep: undefined },
    ),
  setPanel: (panel) => set({ panel }),
  dismissLinkNotice: () => set({ linkNotice: undefined }),
  restore: ({
    from,
    to,
    avoidStairs,
    activeStep,
    panel = 'directions',
    linkNotice,
  }) =>
    set({
      from,
      to,
      avoidStairs,
      activeStep: from && to ? activeStep : undefined,
      exploreNodeId: undefined,
      panel,
      linkNotice,
    }),
  relabel: (names) =>
    set((s) => ({
      from: s.from && names.from ? { ...s.from, name: names.from } : s.from,
      to: s.to && names.to ? { ...s.to, name: names.to } : s.to,
    })),
}));
