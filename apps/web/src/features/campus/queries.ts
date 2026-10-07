'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import type { paths } from '@/lib/api/schema';
import { assetBaseUrl } from '@/lib/assets';

import {
  parseGraph,
  type Building,
  type CampusGraph,
  type Greenery,
  type Ground,
} from './types';

type JsonOk<T> = T extends {
  responses: { 200: { content: { 'application/json': infer R } } };
}
  ? R
  : never;

export type RouteResponse = JsonOk<paths['/route']['post']>;
export type RouteStep = RouteResponse['steps'][number];
export type Place = JsonOk<paths['/places']['get']>[number];

export class RouteError extends Error {
  constructor(
    readonly kind: 'no_route' | 'unknown_place' | 'unavailable',
    message: string,
  ) {
    super(message);
  }
}

export function useCampusGraph() {
  return useQuery<CampusGraph>({
    queryKey: ['graph'],
    queryFn: async () => {
      const { data, error } = await api.GET('/graph');
      if (error || !data)
        throw new RouteError('unavailable', 'graph not available');
      return parseGraph(data as Parameters<typeof parseGraph>[0]);
    },
    staleTime: Infinity,
  });
}

export function useBuildings() {
  return useQuery<Building[]>({
    queryKey: ['buildings'],
    queryFn: async () => {
      const response = await fetch(`${assetBaseUrl}/buildings.json`);
      if (!response.ok)
        throw new Error(`buildings.json: HTTP ${response.status}`);
      const body = (await response.json()) as { buildings: Building[] };
      return body.buildings;
    },
    staleTime: Infinity,
  });
}

export function useGreenery() {
  return useQuery<Greenery>({
    queryKey: ['greenery'],
    queryFn: async () => {
      const response = await fetch(`${assetBaseUrl}/greenery.json`);
      if (!response.ok)
        throw new Error(`greenery.json: HTTP ${response.status}`);
      return (await response.json()) as Greenery;
    },
    staleTime: Infinity,
  });
}

export function useGround() {
  return useQuery<Ground>({
    queryKey: ['ground'],
    queryFn: async () => {
      const response = await fetch(`${assetBaseUrl}/ground.json`);
      if (!response.ok) throw new Error(`ground.json: HTTP ${response.status}`);
      return (await response.json()) as Ground;
    },
    staleTime: Infinity,
    retry: false,
  });
}

export function usePlaces(query: string) {
  const q = query.trim();
  return useQuery<Place[]>({
    queryKey: ['places', q],
    queryFn: async () => {
      const { data, error } = await api.GET('/places', {
        params: { query: { q, limit: 8 } },
      });
      if (error || !data)
        throw new RouteError('unavailable', 'places not available');
      // openapi-fetch widens the [east, north] pin to number[]; same payload.
      return data as Place[];
    },
    enabled: q.length > 0,
    placeholderData: keepPreviousData,
  });
}

/** Directory entries the API returns at most (its `limit` bound). */
const DIRECTORY_LIMIT = 50;

/**
 * Every place the map shows, for suggestions before the visitor types and
 * for the map's business pins (every business or service with a pin).
 */
export function usePlaceDirectory() {
  return useQuery<Place[]>({
    queryKey: ['places', '*'],
    queryFn: async () => {
      const { data, error } = await api.GET('/places', {
        params: { query: { q: '', limit: DIRECTORY_LIMIT } },
      });
      if (error || !data)
        throw new RouteError('unavailable', 'places not available');
      return data as Place[];
    },
    staleTime: Infinity,
  });
}

/** Longest wait for a route before the panel offers to try again. */
const ROUTE_TIMEOUT_MS = 15_000;

export function useRoute(
  source: string | undefined,
  target: string | undefined,
  avoidStairs: boolean,
) {
  return useQuery<RouteResponse>({
    queryKey: ['route', source, target, avoidStairs],
    queryFn: async ({ signal }) => {
      // A server that never answers must not keep the panel loading forever.
      const timeout = AbortSignal.timeout(ROUTE_TIMEOUT_MS);
      const result = await api
        .POST('/route', {
          body: {
            source: source!,
            target: target!,
            avoid_stairs: avoidStairs,
          },
          signal:
            typeof AbortSignal.any === 'function'
              ? AbortSignal.any([signal, timeout])
              : timeout,
        })
        .catch((cause: unknown) => {
          if (signal.aborted) throw cause;
          throw new RouteError('unavailable', `route: ${String(cause)}`);
        });
      const { data, error, response } = result;
      // openapi-fetch widens the [lng, lat] tuples to number[][]; same payload.
      if (data) return data as RouteResponse;
      if (response.status === 422)
        throw new RouteError('no_route', String(error?.detail ?? ''));
      if (response.status === 404)
        throw new RouteError('unknown_place', String(error?.detail ?? ''));
      throw new RouteError('unavailable', `route: HTTP ${response.status}`);
    },
    enabled: Boolean(source && target && source !== target),
    retry: false,
  });
}
