import { redirect } from '@/i18n/navigation';

type Props = { params: Promise<{ locale: string }> };

// The cinematic landing page arrives in phase 6; until then go straight to the map.
export default async function Home({ params }: Props) {
  const { locale } = await params;
  redirect({ href: '/map', locale: locale === 'en' ? 'en' : 'tr' });
}
