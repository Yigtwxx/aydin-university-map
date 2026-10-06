'use client';

import { cn } from 'cn';
import { Check, Link2, TriangleAlert } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { copyText } from '@/lib/clipboard';

import { useRouteStore } from './store';
import { routeParamsOf, shareUrl } from './urlState';

export type CopyState = 'idle' | 'copied' | 'failed';

/** Back to the plain icon after the confirmation has been read. */
const CONFIRM_MS = 2200;

/** Copies an absolute link to the route on screen; the state resets itself. */
export function useCopyLink() {
  const [state, setState] = useState<CopyState>('idle');

  useEffect(() => {
    if (state === 'idle') return;
    const timer = window.setTimeout(() => setState('idle'), CONFIRM_MS);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = useCallback(async () => {
    const link = shareUrl(
      window.location.href,
      routeParamsOf(useRouteStore.getState()),
    );
    setState((await copyText(link)) ? 'copied' : 'failed');
  }, []);

  return { state, copy };
}

/**
 * "Copy link": a square icon button. With `expand` it widens into a short
 * confirmation; without, the caller shows the confirmation next to it (the
 * sheet's one-row summary has no room to widen). A polite live region says
 * the same for screen readers either way.
 */
export function CopyLinkButton({
  link,
  expand = true,
  className,
}: {
  link: ReturnType<typeof useCopyLink>;
  expand?: boolean;
  className?: string;
}) {
  const t = useTranslations('Route');
  const { state, copy } = link;
  const Icon =
    state === 'copied' ? Check : state === 'failed' ? TriangleAlert : Link2;
  const shown = expand && state !== 'idle';

  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              onClick={() => void copy()}
              aria-label={t('copyLink')}
              data-state={state}
              className={cn(
                'flex h-10 min-w-10 shrink-0 items-center justify-center rounded-control bg-fill px-2.5 text-md font-medium text-ink',
                'transition-[background-color,color,transform] duration-200 ease-out-soft hover:bg-fill-strong active:scale-[0.97]',
                state === 'copied' && 'text-route',
                state === 'failed' && 'text-brick',
                className,
              )}
            />
          }
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          {expand && (
            <span
              aria-hidden
              className={cn(
                'overflow-hidden whitespace-nowrap transition-[max-width,opacity,margin] duration-200 ease-out-soft',
                shown
                  ? 'ml-1.5 max-w-32 opacity-100'
                  : 'ml-0 max-w-0 opacity-0',
              )}
            >
              {state === 'failed' ? t('copyFailed') : t('copied')}
            </span>
          )}
        </TooltipTrigger>
        <TooltipContent side="top" sideOffset={8}>
          {t('copyLink')}
        </TooltipContent>
      </Tooltip>
      <span role="status" className="sr-only">
        {state === 'copied'
          ? t('linkCopied')
          : state === 'failed'
            ? t('linkCopyFailed')
            : ''}
      </span>
    </>
  );
}
