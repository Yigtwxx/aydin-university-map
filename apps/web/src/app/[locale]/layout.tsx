import type { Metadata, Viewport } from 'next';
import { Geist } from 'next/font/google';
import { notFound } from 'next/navigation';
import { hasLocale, NextIntlClientProvider } from 'next-intl';
import { getTranslations, setRequestLocale } from 'next-intl/server';

import { routing } from '@/i18n/routing';

import '../globals.css';

// One grotesk for everything (docs/design-system.md#type); latin-ext carries
// ı, ğ, ş and İ. Variable weight, so 400/500/600 cost a single file.
const geist = Geist({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-geist',
  display: 'swap',
});

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: LayoutProps<'/[locale]'>): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({
    locale: hasLocale(routing.locales, locale) ? locale : routing.defaultLocale,
    namespace: 'Meta',
  });
  const title = t('title');
  return {
    // Pages under it (the 404) read "Sayfa bulunamadı · Aydın Kampüs Haritası".
    title: { default: title, template: `%s · ${title}` },
    description: t('description'),
    applicationName: title,
    openGraph: { title, description: t('description'), siteName: title },
  };
}

/**
 * Edge to edge on notched phones (the sheet pads its content above the home
 * indicator), and browser chrome in the stone of the day and night themes
 * (`--stone` in globals.css).
 */
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#e6e8eb' },
    { media: '(prefers-color-scheme: dark)', color: '#0b1018' },
  ],
};

export default async function LocaleLayout({
  children,
  params,
}: LayoutProps<'/[locale]'>) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }
  setRequestLocale(locale);
  return (
    <html lang={locale} className={geist.variable}>
      <body>
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
