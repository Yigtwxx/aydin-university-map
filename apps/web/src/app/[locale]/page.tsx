import { notFound } from 'next/navigation';
import { hasLocale } from 'next-intl';
import { setRequestLocale } from 'next-intl/server';

import { QueryProvider } from '@/app/providers/QueryProvider';
import { MapApp } from '@/features/map/MapApp';
import { routing } from '@/i18n/routing';

/**
 * The map, opening with the campus built out of a dot map. The scroll dive
 * over İstanbul (`intro="dive"`) is off until it can be a pre-rendered
 * Google Earth Studio video: the real-time version did not reach video
 * quality.
 */
export default async function Home({ params }: PageProps<'/[locale]'>) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  return (
    <QueryProvider>
      <MapApp intro="assemble" />
    </QueryProvider>
  );
}
