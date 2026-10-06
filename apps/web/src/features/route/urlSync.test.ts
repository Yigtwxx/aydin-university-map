import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useRouteStore } from './store';
import { createRouteUrlSync, type UrlWrite } from './urlSync';

const NAMES: Record<string, string> = {
  scene_a: 'Kampüs Girişi',
  scene_e: 'E Blok Giriş',
};
const resolve = (id: string) => NAMES[id];

/** A fake address bar wired the way `RouteUrlSync` wires the real one. */
function harness() {
  const sync = createRouteUrlSync(useRouteStore);
  let query = '';
  const writes: UrlWrite[] = [];
  const unsubscribe = useRouteStore.subscribe((state, prev) => {
    const change = sync.storeChanged(state, prev, query);
    if (change) {
      writes.push(change);
      query = change.query;
    }
  });
  return {
    sync,
    writes,
    get query() {
      return query;
    },
    /** The address bar changes (load, back/forward), then the app reacts. */
    navigate(next: string, graphLoaded = true) {
      query = next;
      const cleanup = sync.applyUrl(next, graphLoaded ? resolve : undefined);
      if (cleanup) {
        writes.push(cleanup);
        query = cleanup.query;
      }
    },
    /** Next.js echoes our own writes back through `useSearchParams`. */
    echo() {
      return sync.applyUrl(query, resolve);
    },
    unsubscribe,
  };
}

const initial = useRouteStore.getState();
let h: ReturnType<typeof harness>;

beforeEach(() => {
  useRouteStore.setState(initial, true);
  h = harness();
});
afterEach(() => h.unsubscribe());

describe('URL to store', () => {
  it('restores a shared route with names, the step and the stairs switch', () => {
    h.navigate('from=scene_a&to=scene_e&step=2&stairs=1');
    const state = useRouteStore.getState();
    expect(state.from).toEqual({ id: 'scene_a', name: 'Kampüs Girişi' });
    expect(state.to).toEqual({ id: 'scene_e', name: 'E Blok Giriş' });
    expect(state.activeStep).toBe(2);
    expect(state.avoidStairs).toBe(true);
    // Already canonical: restoring writes nothing back.
    expect(h.writes).toEqual([]);
  });

  it('waits for the graph before restoring names', () => {
    h.navigate('from=scene_a&to=scene_e&stairs=0', false);
    expect(useRouteStore.getState().to).toBeUndefined();
    h.navigate('from=scene_a&to=scene_e&stairs=0');
    expect(useRouteStore.getState().to?.name).toBe('E Blok Giriş');
  });

  it('drops places the graph does not know and cleans the URL', () => {
    h.navigate('to=scene_e&from=nope&utm=x');
    expect(useRouteStore.getState().from).toBeUndefined();
    expect(useRouteStore.getState().to?.id).toBe('scene_e');
    expect(h.writes).toEqual([
      { query: 'utm=x&to=scene_e&stairs=0', mode: 'replace' },
    ]);
  });

  it('says so when a shared place is gone, until a place is picked', () => {
    h.navigate('from=gone&to=missing&stairs=0');
    expect(useRouteStore.getState().linkNotice).toBe('missingPlace');
    expect(useRouteStore.getState().to).toBeUndefined();
    useRouteStore.getState().setTo({ id: 'scene_e', name: 'E Blok Giriş' });
    expect(useRouteStore.getState().linkNotice).toBeUndefined();
  });

  it('raises no notice for a link whose places all exist', () => {
    h.navigate('from=scene_a&to=scene_e&stairs=0');
    expect(useRouteStore.getState().linkNotice).toBeUndefined();
  });

  it('opens the assistant tab from ?panel=assistant, and back', () => {
    h.navigate('panel=assistant');
    expect(useRouteStore.getState().panel).toBe('assistant');
    h.navigate('');
    expect(useRouteStore.getState().panel).toBe('directions');
  });

  it('clears the route when going back to a URL without one', () => {
    h.navigate('from=scene_a&to=scene_e&stairs=0');
    h.navigate('');
    expect(useRouteStore.getState().from).toBeUndefined();
    expect(useRouteStore.getState().to).toBeUndefined();
  });
});

describe('store to URL', () => {
  it('pushes a new route and replaces while stepping through it', () => {
    const { setTo, setFrom, setActiveStep } = useRouteStore.getState();
    setTo({ id: 'scene_e', name: 'E Blok Giriş' });
    setFrom({ id: 'scene_a', name: 'Kampüs Girişi' });
    setActiveStep(0);
    setActiveStep(1);
    expect(h.writes).toEqual([
      { query: 'to=scene_e&stairs=0', mode: 'replace' },
      { query: 'from=scene_a&to=scene_e&stairs=0', mode: 'push' },
      { query: 'from=scene_a&to=scene_e&step=0&stairs=0', mode: 'replace' },
      { query: 'from=scene_a&to=scene_e&step=1&stairs=0', mode: 'replace' },
    ]);
  });

  it('replaces for the stairs switch and pushes for a swap', () => {
    h.navigate('from=scene_a&to=scene_e&stairs=0');
    useRouteStore.getState().setAvoidStairs(true);
    useRouteStore.getState().swap();
    expect(h.writes).toEqual([
      { query: 'from=scene_a&to=scene_e&stairs=1', mode: 'replace' },
      { query: 'from=scene_e&to=scene_a&stairs=1', mode: 'push' },
    ]);
  });

  it('does not apply its own writes back to the store', () => {
    const { setTo, setFrom } = useRouteStore.getState();
    setTo({ id: 'scene_e', name: 'E Blok Giriş' });
    setFrom({ id: 'scene_a', name: 'Kampüs Girişi' });
    const before = useRouteStore.getState();
    expect(h.echo()).toBeUndefined();
    expect(useRouteStore.getState()).toBe(before);
  });

  it('ignores renames, which do not change the URL', () => {
    h.navigate('from=scene_a&to=scene_e&stairs=0');
    useRouteStore.getState().relabel({ to: 'E Block Entrance' });
    expect(h.writes).toEqual([]);
    expect(useRouteStore.getState().to?.name).toBe('E Block Entrance');
  });

  it('mirrors the tab, keeping the route', () => {
    h.navigate('from=scene_a&to=scene_e&stairs=0');
    useRouteStore.getState().setPanel('assistant');
    useRouteStore.getState().setPanel('directions');
    expect(h.writes).toEqual([
      {
        query: 'from=scene_a&to=scene_e&stairs=0&panel=assistant',
        mode: 'replace',
      },
      { query: 'from=scene_a&to=scene_e&stairs=0', mode: 'replace' },
    ]);
  });

  it('clears the route parameters when the route is cleared', () => {
    h.navigate('from=scene_a&to=scene_e&stairs=0&utm=x');
    useRouteStore.getState().restore({ avoidStairs: false });
    expect(h.query).toBe('utm=x');
  });
});
