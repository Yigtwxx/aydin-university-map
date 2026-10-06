import { create } from 'zustand';

export interface PlaceRef {
  id: string;
  name: string;
}

interface RouteState {
  from?: PlaceRef;
  to?: PlaceRef;
  avoidStairs: boolean;
  /** Index into the route's steps; drives the camera and the 360° inset. */
  activeStep?: number;
  /** A 360° spot opened from the map without following a route. */
  exploreNodeId?: string;
  setFrom: (place?: PlaceRef) => void;
  setTo: (place?: PlaceRef) => void;
  swap: () => void;
  setAvoidStairs: (value: boolean) => void;
  setActiveStep: (index?: number) => void;
  setExploreNode: (nodeId?: string) => void;
}

export const useRouteStore = create<RouteState>((set) => ({
  from: undefined,
  to: undefined,
  avoidStairs: false,
  activeStep: undefined,
  exploreNodeId: undefined,
  setFrom: (from) => set({ from, activeStep: undefined }),
  setTo: (to) => set({ to, activeStep: undefined, exploreNodeId: undefined }),
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
}));
