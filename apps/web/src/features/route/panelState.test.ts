import { describe, expect, it } from 'vitest';

import { RouteError } from '@/features/campus/queries';

import { canRetry, panelState, routeProblem } from './panelState';

const a = { id: 'scene_a', name: 'Kampüs Girişi' };
const e = { id: 'scene_e', name: 'E Blok Giriş' };
const idle = { loading: false, paused: false, hasRoute: false };

describe('panelState', () => {
  it('browses with no ends and asks for the missing one', () => {
    expect(panelState({ ...idle })).toBe('browse');
    expect(panelState({ ...idle, to: e })).toBe('pickStart');
    // A route whose destination was cleared asks for a destination.
    expect(panelState({ ...idle, from: a })).toBe('pickDestination');
  });

  it('never waits on a route that cannot be requested', () => {
    expect(panelState({ ...idle, from: a, to: a })).toBe('samePlace');
    expect(panelState({ ...idle, from: a, to: e, paused: true })).toBe(
      'offline',
    );
  });

  it('loads, then shows the route or the error', () => {
    const both = { ...idle, from: a, to: e };
    expect(panelState({ ...both, loading: true })).toBe('loading');
    expect(panelState({ ...both, hasRoute: true })).toBe('route');
    expect(panelState({ ...both, error: new Error('down') })).toBe('error');
    // A retry in flight shows the skeleton, not the old error.
    expect(
      panelState({ ...both, loading: true, error: new Error('down') }),
    ).toBe('loading');
  });
});

describe('routeProblem', () => {
  it('tells a missing step-free way from a missing way', () => {
    const none = new RouteError('no_route', '');
    expect(routeProblem('error', none, true)).toBe('noStepFree');
    expect(routeProblem('error', none, false)).toBe('noRoute');
    expect(canRetry('noStepFree')).toBe(false);
  });

  it('offers a retry when the network or the service failed', () => {
    expect(routeProblem('offline', undefined, false)).toBe('offline');
    expect(routeProblem('error', new TypeError('fetch'), false)).toBe(
      'unavailable',
    );
    expect(
      routeProblem('error', new RouteError('unavailable', 'HTTP 502'), false),
    ).toBe('unavailable');
    expect(canRetry('offline')).toBe(true);
    expect(canRetry('unavailable')).toBe(true);
  });

  it('does not retry a place the graph no longer has', () => {
    const gone = new RouteError('unknown_place', '');
    expect(routeProblem('error', gone, false)).toBe('unknownPlace');
    expect(canRetry('unknownPlace')).toBe(false);
  });
});
