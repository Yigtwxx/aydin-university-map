import { notFound } from 'next/navigation';
import { hasLocale } from 'next-intl';
import { setRequestLocale } from 'next-intl/server';

import { QueryProvider } from '@/app/providers/QueryProvider';
import { MapApp } from '@/features/map/MapApp';
import { routing } from '@/i18n/routing';

/** The dive over İstanbul, flowing straight into the map. */
export default async function Home({ params }: PageProps<'/[locale]'>) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  return (
    <QueryProvider>
      <MapApp intro />
    </QueryProvider>
  );
}
