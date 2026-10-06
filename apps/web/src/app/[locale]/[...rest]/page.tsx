import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { hasLocale } from 'next-intl';
import { getTranslations } from 'next-intl/server';

import { routing } from '@/i18n/routing';

/** Any path the app does not have: the localized 404 (`../not-found.tsx`). */
export async function generateMetadata({
  params,
}: PageProps<'/[locale]/[...rest]'>): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({
    locale: hasLocale(routing.locales, locale) ? locale : routing.defaultLocale,
    namespace: 'NotFound',
  });
  return { title: t('title') };
}

// The locale layout already set the request locale.
export default function CatchAll() {
  notFound();
}
