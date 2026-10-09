import { RouteError } from '@/features/campus/queries';

import type { PlaceRef } from './store';

/** What the directions panel shows under its fields. */
export type PanelState =
  | 'browse'
  | 'pickStart'
  | 'pickDestination'
  | 'samePlace'
  | 'loading'
  | 'offline'
  | 'error'
  | 'route';

export interface PanelInputs {
  from?: PlaceRef;
  to?: PlaceRef;
  /** The route request is in flight. */
  loading: boolean;
  /** The request waits for the network (react-query pauses it offline). */
  paused: boolean;
  error?: unknown;
  hasRoute: boolean;
}

/**
 * Every combination ends somewhere a visitor can act: a missing end asks for
 * that end (a cleared destination never asks for the start), and a request
 * that cannot run (the same place twice, offline) says so instead of leaving
 * the skeleton on screen.
 */
export function panelState({
  from,
  to,
  loading,
  paused,
  error,
  hasRoute,
}: PanelInputs): PanelState {
  if (!from && !to) return 'browse';
  if (!to) return 'pickDestination';
  if (!from) return 'pickStart';
  // The route query never runs for these: no answer would ever come.
  if (from.id === to.id) return 'samePlace';
  if (loading) return 'loading';
  if (error) return 'error';
  if (paused) return 'offline';
  return hasRoute ? 'route' : 'loading';
}

/** How a failed route is explained, and what the panel offers next. */
export type RouteProblem =
  | 'detached'
  | 'noStepFree'
  | 'noRoute'
  | 'unknownPlace'
  | 'offline'
  | 'unavailable';

export function routeProblem(
  state: 'offline' | 'error',
  error: unknown,
  avoidStairs: boolean,
): RouteProblem {
  if (state === 'offline') return 'offline';
  if (error instanceof RouteError) {
    // No ramp would help: the street walk between them is not on the map.
    if (error.kind === 'detached') return 'detached';
    // Indoors there is no lift data: say why, not "no way".
    if (error.kind === 'no_route')
      return avoidStairs ? 'noStepFree' : 'noRoute';
    if (error.kind === 'unknown_place') return 'unknownPlace';
  }
  return 'unavailable';
}

/** Problems a second try can fix (the network, the service). */
export function canRetry(problem: RouteProblem): boolean {
  return problem === 'offline' || problem === 'unavailable';
}
