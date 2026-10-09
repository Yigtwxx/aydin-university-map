import { ArrowLeft } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { RouteMark } from '@/components/brand/RouteMark';
import { Link } from '@/i18n/navigation';

/**
 * The 404 inside a locale: unknown paths (`[...rest]`) and unknown locales,
 * which the middleware sends to `/tr/<path>`. In the map's own materials:
 * stone, a thick glass card, the route colour for the way back.
 */
export default function NotFound() {
  const t = useTranslations('NotFound');
  const brand = useTranslations('Brand');
  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-stone px-4 py-10">
      {/* The dot field the campus is built from in the opening, fading out
          towards the edges. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(var(--ink-faint)_1px,transparent_1.5px)] [mask-image:radial-gradient(ellipse_at_center,#000_10%,transparent_70%)] [background-size:18px_18px] opacity-60"
      />
      <section
        aria-labelledby="not-found-title"
        className="glass glass-thick relative flex w-full max-w-sm flex-col items-start gap-5 rounded-[22px] p-6"
      >
        <span className="flex size-9 items-center justify-center rounded-[10px] bg-ink text-stone-raised shadow-thumb [--mark-accent:var(--ice-inverse)]">
          <RouteMark className="size-5" />
        </span>
        <div className="flex flex-col gap-2">
          <p className="tabular text-xs font-semibold tracking-heading text-ink-muted">
            404 · {brand('short')}
          </p>
          <h1
            id="not-found-title"
            className="text-2xl leading-tight font-semibold tracking-display"
          >
            {t('title')}
          </h1>
          <p className="text-sm leading-relaxed text-ink-muted">{t('body')}</p>
        </div>
        <Link
          href="/map"
          className="flex h-10 items-center gap-2 rounded-control bg-route pr-4 pl-3.5 text-md font-medium text-on-route shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_6px_16px_-8px_var(--route)] transition-[filter,transform] duration-150 ease-out-soft hover:brightness-110 active:scale-[0.985]"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t('back')}
        </Link>
      </section>
    </main>
  );
}
