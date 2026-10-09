'use client';

import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useCallback } from 'react';

import { api } from '@/lib/api/client';
import type { paths } from '@/lib/api/schema';
import { assetBaseUrl } from '@/lib/assets';

import { type Furniture, fetchFurniture } from './furniture';
import { detachedEnd, onMainNetwork, walkNetworkOf } from './network';
import { type Terrain, terrainOf } from './terrain';
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
  /**
   * `detached`: one end lies off the campus walking network (the message is
   * that end's place id).
   */
  constructor(
    readonly kind: 'no_route' | 'detached' | 'unknown_place' | 'unavailable',
    message: string,
  ) {
    super(message);
  }
}

/**
 * The walking graph, straight from the asset host: the same file the API
 * loads, so the map never waits on an API cold start to appear.
 */
export function useCampusGraph() {
  return useQuery<CampusGraph>({
    queryKey: ['graph'],
    queryFn: async () => {
      // Revalidate (304 when unchanged): a graph published since the last
      // visit must not meet routes from the new one.
      const response = await fetch(`${assetBaseUrl}/graph.geojson`, {
        cache: 'no-cache',
      }).catch((cause: unknown) => {
        throw new RouteError('unavailable', `graph: ${String(cause)}`);
      });
      if (!response.ok)
        throw new RouteError('unavailable', `graph: HTTP ${response.status}`);
      return parseGraph(
        (await response.json()) as Parameters<typeof parseGraph>[0],
      );
    },
    staleTime: Infinity,
  });
}

/**
 * Whether a walk from the campus reaches a place (the dormitory's island is
 * not reached yet). Every place counts while the graph loads.
 */
export function useOnCampusNetwork(): (place: Place) => boolean {
  const { data: graph } = useCampusGraph();
  // Computed once per graph (walkNetworkOf caches it).
  const network = graph ? walkNetworkOf(graph) : undefined;
  return useCallback(
    (place: Place) => !network || onMainNetwork(network, place.node_ids),
    [network],
  );
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

/**
 * Street furniture and the ground's level changes. Optional: a missing
 * `furniture.json` (404) is an empty collection, not an error.
 */
export function useFurniture() {
  return useQuery<Furniture>({
    queryKey: ['furniture'],
    queryFn: () => fetchFurniture(assetBaseUrl),
    staleTime: Infinity,
    retry: false,
  });
}

/**
 * Ground height at any point (terraces, banks, stairs and ramps); flat until
 * the furniture loads, or when there is none.
 */
export function useTerrain(): Terrain {
  return terrainOf(useFurniture().data);
}

export function usePlaces(query: string) {
  const q = query.trim();
  return useQuery<Place[]>({
    queryKey: ['places', q],
    queryFn: async () => {
      const { data, error } = await api.GET('/places', {
        // Enough to fill the list on a phone; it scrolls past that.
        params: { query: { q, limit: 20 } },
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
  const client = useQueryClient();
  return useQuery<RouteResponse>({
    queryKey: ['route', source, target, avoidStairs],
    queryFn: async ({ signal }) => {
      // Ends on two unconnected parts of the graph (the campus and the
      // dormitory) have no walk between them: say so without asking.
      const graph = client.getQueryData<CampusGraph>(['graph']);
      if (graph) {
        const directory = client.getQueryData<Place[]>(['places', '*']);
        const nodesOf = (id: string) =>
          directory?.find((place) => place.id === id)?.node_ids ?? [id];
        const off = detachedEnd(
          walkNetworkOf(graph),
          nodesOf(source!),
          nodesOf(target!),
        );
        if (off)
          throw new RouteError(
            'detached',
            off === 'source' ? source! : target!,
          );
      }
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
