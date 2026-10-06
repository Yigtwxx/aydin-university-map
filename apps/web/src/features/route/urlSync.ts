/**
 * Two-way sync between the route store and the query string, without React
 * or the router: `RouteUrlSync` reads the URL and performs the writes this
 * returns. It remembers the last query both sides agreed on, so the URL echo
 * of a store write is not applied back to the store.
 */

import type { StoreApi } from 'zustand';

import type { RouteState } from './store';
import {
  parseRouteParams,
  routeParamsOf,
  sameRoute,
  startsNewRoute,
  withRouteParams,
} from './urlState';

/** Display name of a node id, or `undefined` when the graph has no such node. */
export type ResolveName = (id: string) => string | undefined;

export interface UrlWrite {
  /** Query string without `?`. */
  query: string;
  mode: 'push' | 'replace';
}

export function createRouteUrlSync(
  store: Pick<StoreApi<RouteState>, 'getState'>,
) {
  let agreed: string | undefined;
  let applying = false;

  return {
    /**
     * URL → store, on load and on back/forward. A query naming places waits
     * for `resolve` (the graph), so the fields never show bare ids. Unknown
     * places are dropped and flagged (`linkNotice`). Returns a replace when
     * the URL needs cleaning up (unknown places, missing `stairs`),
     * `undefined` otherwise.
     */
    applyUrl(query: string, resolve?: ResolveName): UrlWrite | undefined {
      if (query === agreed) return undefined;
      const params = new URLSearchParams(query);
      const parsed = parseRouteParams(params);
      const state = store.getState();
      if (sameRoute(parsed, routeParamsOf(state))) {
        agreed = query;
        return undefined;
      }
      if ((parsed.from || parsed.to) && !resolve) return undefined;
      const end = (id?: string) => {
        const name = id ? resolve?.(id) : undefined;
        return id && name !== undefined ? { id, name } : undefined;
      };
      const from = end(parsed.from);
      const to = end(parsed.to);
      // Never silently: the visitor followed a link to somewhere specific.
      const missing = (parsed.from && !from) || (parsed.to && !to);
      applying = true;
      try {
        state.restore({
          from,
          to,
          avoidStairs: parsed.stairs,
          activeStep: parsed.step,
          panel: parsed.panel ?? 'directions',
          linkNotice: missing ? 'missingPlace' : undefined,
        });
      } finally {
        applying = false;
      }
      const canonical = withRouteParams(
        params,
        routeParamsOf(store.getState()),
      ).toString();
      agreed = canonical;
      return canonical === query
        ? undefined
        : { query: canonical, mode: 'replace' };
    },

    /** Store → URL; `current` is the live query string without `?`. */
    storeChanged(
      state: RouteState,
      prev: RouteState,
      current: string,
    ): UrlWrite | undefined {
      if (applying) return undefined;
      const next = routeParamsOf(state);
      const before = routeParamsOf(prev);
      if (sameRoute(next, before)) return undefined;
      const query = withRouteParams(current, next).toString();
      agreed = query;
      if (query === current) return undefined;
      return { query, mode: startsNewRoute(before, next) ? 'push' : 'replace' };
    },
  };
}
