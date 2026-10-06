import { notFound } from 'next/navigation';
import { hasLocale } from 'next-intl';
import { setRequestLocale } from 'next-intl/server';

import { QueryProvider } from '@/app/providers/QueryProvider';
import { MapApp } from '@/features/map/MapApp';
import { routing } from '@/i18n/routing';

export default async function MapPage({ params }: PageProps<'/[locale]/map'>) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  return (
    <QueryProvider>
      <MapApp />
    </QueryProvider>
  );
}
