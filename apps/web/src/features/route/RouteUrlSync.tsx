'use client';

import { useSearchParams } from 'next/navigation';
import { useLocale } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useCampusGraph, usePlaceDirectory } from '@/features/campus/queries';
import { getPathname, usePathname } from '@/i18n/navigation';

import { useRouteStore } from './store';
import { placeName } from './urlState';
import { createRouteUrlSync, type UrlWrite } from './urlSync';

/**
 * Keeps `?from&to&step&stairs` and the route store in step, both ways.
 * Renders nothing; mount it inside a `<Suspense>` (it reads the query string,
 * which a prerendered page only knows in the browser).
 */
export function RouteUrlSync() {
  const searchParams = useSearchParams();
  const locale = useLocale();
  const pathname = usePathname();
  const graph = useCampusGraph();
  const directory = usePlaceDirectory();
  const from = useRouteStore((s) => s.from);
  const to = useRouteStore((s) => s.to);
  const relabel = useRouteStore((s) => s.relabel);
  const [sync] = useState(() => createRouteUrlSync(useRouteStore));

  const nodes = graph.data?.byId;
  const nameOf = useCallback(
    (id: string) => placeName(id, locale, directory.data, nodes),
    [locale, directory.data, nodes],
  );
  // Only places the graph knows are restored; ids are never routed blindly.
  const resolve = useMemo(
    () =>
      nodes
        ? (id: string) => (nodes.has(id) ? (nameOf(id) ?? id) : undefined)
        : undefined,
    [nodes, nameOf],
  );

  // The native history API is what Next.js syncs `useSearchParams` with, and
  // unlike `router.replace` it costs no server round trip per step.
  const write = useCallback(
    ({ query, mode }: UrlWrite) => {
      const href = getPathname({
        href: {
          pathname,
          query: Object.fromEntries(new URLSearchParams(query)),
        },
        locale,
      });
      if (mode === 'push') window.history.pushState(null, '', href);
      else window.history.replaceState(null, '', href);
    },
    [pathname, locale],
  );

  // URL → store: a shared link on load, back and forward afterwards.
  useEffect(() => {
    const cleanup = sync.applyUrl(searchParams.toString(), resolve);
    if (cleanup) write(cleanup);
  }, [searchParams, resolve, sync, write]);

  // Store → URL: picks, swaps, the stairs switch and every step.
  useEffect(
    () =>
      useRouteStore.subscribe((state, prev) => {
        const change = sync.storeChanged(
          state,
          prev,
          window.location.search.replace(/^\?/, ''),
        );
        if (change) write(change);
      }),
    [sync, write],
  );

  // Names follow the language (a link shared in Turkish opens in English).
  useEffect(() => {
    if (!nodes) return;
    const names = {
      from: from ? nameOf(from.id) : undefined,
      to: to ? nameOf(to.id) : undefined,
    };
    if (
      (names.from && names.from !== from?.name) ||
      (names.to && names.to !== to?.name)
    )
      relabel(names);
  }, [from, to, nodes, nameOf, relabel]);

  return null;
}
