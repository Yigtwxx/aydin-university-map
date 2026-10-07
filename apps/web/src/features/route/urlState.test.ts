import { describe, expect, it } from 'vitest';

import type { Place } from '@/features/campus/queries';
import type { GraphNode } from '@/features/campus/types';

import {
  parseRouteParams,
  isKnownPlace,
  placeName,
  routeParamsOf,
  sameRoute,
  shareUrl,
  startsNewRoute,
  withRouteParams,
} from './urlState';

const params = (query: string) => new URLSearchParams(query);

describe('parseRouteParams', () => {
  it('reads both ends, the step and the stairs switch', () => {
    expect(
      parseRouteParams(params('from=scene_1&to=scene_2&step=3&stairs=1')),
    ).toEqual({ from: 'scene_1', to: 'scene_2', step: 3, stairs: true });
  });

  it('defaults to no route and stairs allowed', () => {
    expect(parseRouteParams(params(''))).toEqual({
      from: undefined,
      to: undefined,
      step: undefined,
      stairs: false,
    });
    expect(parseRouteParams(params('stairs=0')).stairs).toBe(false);
  });

  it('ignores malformed ids and steps', () => {
    const parsed = parseRouteParams(
      params('from=../etc&to=<script>&step=-1&stairs=yes'),
    );
    expect(parsed).toEqual({
      from: undefined,
      to: undefined,
      step: undefined,
      stairs: false,
    });
    expect(
      parseRouteParams(params('from=a&to=b&step=1e3')).step,
    ).toBeUndefined();
  });

  it('reads the assistant tab, and only that value', () => {
    expect(parseRouteParams(params('panel=assistant')).panel).toBe('assistant');
    expect(parseRouteParams(params('panel=evil')).panel).toBeUndefined();
  });

  it('keeps a step only for a complete route', () => {
    expect(parseRouteParams(params('to=scene_2&step=2')).step).toBeUndefined();
  });
});

describe('routeParamsOf', () => {
  it('maps the store and drops the step of a half-picked route', () => {
    expect(
      routeParamsOf({
        from: { id: 'a', name: 'A' },
        to: { id: 'b', name: 'B' },
        activeStep: 0,
        avoidStairs: true,
      }),
    ).toEqual({ from: 'a', to: 'b', step: 0, stairs: true });
    expect(
      routeParamsOf({
        to: { id: 'b', name: 'B' },
        activeStep: 2,
        avoidStairs: false,
      }).step,
    ).toBeUndefined();
  });
});

describe('withRouteParams', () => {
  it('writes the route in a stable order and keeps other parameters', () => {
    expect(
      withRouteParams('utm=x&step=9', {
        from: 'a',
        to: 'b',
        step: 1,
        stairs: false,
      }).toString(),
    ).toBe('utm=x&from=a&to=b&step=1&stairs=0');
  });

  it('leaves no route parameters for an empty route', () => {
    expect(
      withRouteParams('from=a&to=b&stairs=1', { stairs: true }).toString(),
    ).toBe('');
  });

  it('spells out the assistant tab with or without a route', () => {
    expect(
      withRouteParams('', { stairs: false, panel: 'assistant' }).toString(),
    ).toBe('panel=assistant');
    expect(
      withRouteParams('panel=assistant', {
        to: 'b',
        stairs: false,
      }).toString(),
    ).toBe('to=b&stairs=0');
  });

  it('round-trips through parseRouteParams', () => {
    const route = { from: 'scene_1', to: 'scene_2', step: 4, stairs: true };
    expect(parseRouteParams(withRouteParams('', route))).toEqual(route);
  });
});

describe('sameRoute and startsNewRoute', () => {
  const route = { from: 'a', to: 'b', step: 1, stairs: false };

  it('compares every field', () => {
    expect(sameRoute(route, { ...route })).toBe(true);
    expect(sameRoute(route, { ...route, step: 2 })).toBe(false);
    expect(sameRoute(route, { ...route, stairs: true })).toBe(false);
  });

  it('pushes only for a complete route with new ends', () => {
    expect(startsNewRoute({ stairs: false }, route)).toBe(true);
    expect(startsNewRoute(route, { ...route, from: 'c' })).toBe(true);
    expect(startsNewRoute(route, { ...route, step: 3 })).toBe(false);
    expect(startsNewRoute(route, { ...route, stairs: true })).toBe(false);
    expect(startsNewRoute({ stairs: false }, { to: 'b', stairs: false })).toBe(
      false,
    );
  });
});

describe('shareUrl', () => {
  it('builds an absolute link from the current page', () => {
    expect(
      shareUrl('https://map.example/tr/map?step=2#x', {
        from: 'a',
        to: 'b',
        stairs: true,
      }),
    ).toBe('https://map.example/tr/map?from=a&to=b&stairs=1');
  });
});

describe('placeName', () => {
  const places = [
    { id: 'p1', name_tr: 'E Blok Giriş', name_en: 'E Block Entrance' },
  ] as Place[];
  const nodes = new Map([
    ['n1', { id: 'n1', label: { tr: 'Kampüs', en: 'Campus' } } as GraphNode],
  ]);

  it('prefers the place directory, in the requested language', () => {
    expect(placeName('p1', 'tr', places, nodes)).toBe('E Blok Giriş');
    expect(placeName('p1', 'en', places, nodes)).toBe('E Block Entrance');
  });

  it('falls back to the node label, then to nothing', () => {
    expect(placeName('n1', 'en', places, nodes)).toBe('Campus');
    expect(placeName('n1', 'tr', undefined, nodes)).toBe('Kampüs');
    expect(placeName('zz', 'tr', places, nodes)).toBeUndefined();
  });
});

describe('isKnownPlace', () => {
  const places = [
    { id: 'n1', name_tr: 'Kampüs', name_en: 'Campus' },
    { id: 'poi:atm', name_tr: 'ATM', name_en: 'ATM' },
  ] as Place[];
  const nodes = new Map([['n1', { id: 'n1' } as GraphNode]]);

  it('knows graph nodes and the directory’s businesses without a node', () => {
    expect(isKnownPlace('n1', places, nodes)).toBe(true);
    expect(isKnownPlace('poi:atm', places, nodes)).toBe(true);
    expect(isKnownPlace('poi:gone', places, nodes)).toBe(false);
  });

  it('knows only nodes while the directory is missing', () => {
    expect(isKnownPlace('n1', undefined, nodes)).toBe(true);
    expect(isKnownPlace('poi:atm', undefined, nodes)).toBe(false);
  });
});
