/**
 * Shareable routes: `?from=<nodeId>&to=<nodeId>&step=<index>&stairs=0|1`,
 * plus `panel=assistant` for the assistant tab.
 * Pure conversions between the query string and the route store, so the
 * two-way sync in `RouteUrlSync` stays a thin shell around them.
 */

import type { Place } from '@/features/campus/queries';
import type { GraphNode } from '@/features/campus/types';

import type { PanelTab, PlaceRef } from './store';

export interface RouteParams {
  from?: string;
  to?: string;
  /** Route step shown in 360°; only meaningful with both ends. */
  step?: number;
  stairs: boolean;
  /** Only the non-default tab is spelled out. */
  panel?: 'assistant';
}

/** The parts of the route store that live in the URL. */
export interface RouteSnapshot {
  from?: PlaceRef;
  to?: PlaceRef;
  activeStep?: number;
  avoidStairs: boolean;
  panel?: PanelTab;
}

interface ReadableParams {
  get(name: string): string | null;
}

const KEYS = ['from', 'to', 'step', 'stairs', 'panel'] as const;
/** Graph node ids (`scene_428538`); anything else is ignored, never routed. */
const NODE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const STEP = /^\d{1,3}$/;

function nodeId(value: string | null): string | undefined {
  return value && NODE_ID.test(value) ? value : undefined;
}

export function parseRouteParams(params: ReadableParams): RouteParams {
  const from = nodeId(params.get('from'));
  const to = nodeId(params.get('to'));
  const step = params.get('step');
  return {
    from,
    to,
    step: from && to && step && STEP.test(step) ? Number(step) : undefined,
    stairs: params.get('stairs') === '1',
    panel: params.get('panel') === 'assistant' ? 'assistant' : undefined,
  };
}

export function routeParamsOf(state: RouteSnapshot): RouteParams {
  const both = Boolean(state.from && state.to);
  return {
    from: state.from?.id,
    to: state.to?.id,
    step: both ? state.activeStep : undefined,
    stairs: state.avoidStairs,
    panel: state.panel === 'assistant' ? 'assistant' : undefined,
  };
}

export function sameRoute(a: RouteParams, b: RouteParams): boolean {
  return (
    a.from === b.from &&
    a.to === b.to &&
    a.step === b.step &&
    a.stairs === b.stairs &&
    a.panel === b.panel
  );
}

/**
 * Writes the route into a copy of `base`, keeping unrelated parameters. An
 * empty route leaves no trace; otherwise `stairs` is always spelled out.
 */
export function withRouteParams(
  base: URLSearchParams | string,
  route: RouteParams,
): URLSearchParams {
  const params = new URLSearchParams(base);
  for (const key of KEYS) params.delete(key);
  if (route.from || route.to) {
    if (route.from) params.set('from', route.from);
    if (route.to) params.set('to', route.to);
    if (route.step !== undefined) params.set('step', String(route.step));
    params.set('stairs', route.stairs ? '1' : '0');
  }
  if (route.panel) params.set('panel', route.panel);
  return params;
}

/**
 * A change worth its own history entry: a complete route with a new start or
 * destination. Steps, the stairs switch and half-picked routes replace the
 * current entry, so walking through steps never floods the back button.
 */
export function startsNewRoute(prev: RouteParams, next: RouteParams): boolean {
  return (
    Boolean(next.from && next.to) &&
    (prev.from !== next.from || prev.to !== next.to)
  );
}

/** Absolute link to `href` showing `route` (for "Copy link"). */
export function shareUrl(href: string, route: RouteParams): string {
  const url = new URL(href);
  url.search = withRouteParams(url.search, route).toString();
  url.hash = '';
  return url.toString();
}

/**
 * Whether a shared link's id names a place the map knows: a graph node, or a
 * place the directory lists (a business of its own, `poi:<slug>`, is not a
 * node). Ids are never routed blindly.
 */
export function isKnownPlace(
  id: string,
  places: readonly Place[] | undefined,
  nodes: ReadonlyMap<string, GraphNode> | undefined,
): boolean {
  return Boolean(nodes?.has(id) || places?.some((p) => p.id === id));
}

/**
 * Display name of a route end in `locale`: the place directory first (the
 * names the search shows), else the graph node's own label.
 */
export function placeName(
  id: string,
  locale: string,
  places: readonly Place[] | undefined,
  nodes: ReadonlyMap<string, GraphNode> | undefined,
): string | undefined {
  const place = places?.find((p) => p.id === id);
  if (place) return locale === 'en' ? place.name_en : place.name_tr;
  const node = nodes?.get(id);
  if (node) return locale === 'en' ? node.label.en : node.label.tr;
  return undefined;
}
