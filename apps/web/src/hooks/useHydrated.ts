import { useSyncExternalStore } from 'react';

const subscribeNothing = () => () => {};

/**
 * False in the server render and while hydrating, true from the first client
 * render on. For text that only the browser knows (the time): the page is
 * prerendered and cached, so a server value can be hours old, and hydration
 * keeps whatever the server wrote.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribeNothing,
    () => true,
    () => false,
  );
}
