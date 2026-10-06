'use client';

import { useChat } from '@ai-sdk/react';
import {
  DefaultChatTransport,
  getToolName,
  isToolUIPart,
  type UIMessage,
} from 'ai';
import { ArrowUp, Footprints, Square } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useLocale, useTranslations } from 'next-intl';
import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react';

import { FanMark } from '@/components/brand/FanMark';
import { RichText } from '@/features/chat/RichText';
import { useRouteStore } from '@/features/route/store';
import { apiBaseUrl } from '@/lib/api/client';

const MAX_CHARS = 1000;
const EASE = [0.2, 0.7, 0.2, 1] as const;

interface RouteOutput {
  from: { id: string; name_tr: string; name_en: string };
  to: { id: string; name_tr: string; name_en: string };
  length_m: number;
  duration_min: number;
}

function isRouteOutput(value: unknown): value is RouteOutput {
  return (
    typeof value === 'object' &&
    value !== null &&
    'from' in value &&
    'to' in value &&
    'length_m' in value
  );
}

/** Ask the campus assistant; route answers draw on the map. */
export function AssistantPanel({
  onShowDirections,
}: {
  onShowDirections: () => void;
}) {
  const t = useTranslations('Chat');
  const locale = useLocale();
  const { setFrom, setTo } = useRouteStore();
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${apiBaseUrl}/chat`,
        headers: { 'X-Amap-Locale': locale },
      }),
    [locale],
  );
  const { messages, sendMessage, status, error, stop } = useChat({ transport });
  const [input, setInput] = useState('');
  const applied = useRef(new Set<string>());
  const scroller = useRef<HTMLDivElement>(null);
  const busy = status === 'submitted' || status === 'streaming';

  // A finished get_route call fills the directions, so the map draws it.
  useEffect(() => {
    for (const message of messages) {
      for (const part of message.parts) {
        if (
          isToolUIPart(part) &&
          getToolName(part) === 'get_route' &&
          part.state === 'output-available' &&
          !applied.current.has(part.toolCallId) &&
          isRouteOutput(part.output)
        ) {
          applied.current.add(part.toolCallId);
          const { from, to } = part.output;
          setFrom({
            id: from.id,
            name: locale === 'en' ? from.name_en : from.name_tr,
          });
          setTo({ id: to.id, name: locale === 'en' ? to.name_en : to.name_tr });
        }
      }
    }
  }, [messages, locale, setFrom, setTo]);

  useEffect(() => {
    scroller.current?.scrollTo({
      top: scroller.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages]);

  const ask = (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    void sendMessage({ text: question.slice(0, MAX_CHARS) });
    setInput('');
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    ask(input);
  };

  const suggestions = [t('suggest1'), t('suggest2'), t('suggest3')];

  return (
    <section
      aria-labelledby="assistant-heading"
      className="flex min-h-0 flex-1 flex-col gap-3"
    >
      <h2 id="assistant-heading" className="sr-only">
        {t('title')}
      </h2>
      <div
        ref={scroller}
        aria-live="polite"
        className="flex min-h-0 flex-1 [scrollbar-width:thin] flex-col gap-3 overflow-y-auto overscroll-contain pr-1"
      >
        {messages.length === 0 && (
          <div className="flex flex-col gap-3 px-1 pt-1">
            <p className="text-sm text-ink-muted">{t('intro')}</p>
            <div className="flex flex-col gap-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => ask(s)}
                  className="rounded-xl bg-stone-raised/75 px-3 py-2 text-left text-sm shadow-[inset_0_0_0_1px_var(--hairline)] transition-colors duration-150 ease-out-soft hover:bg-stone-raised"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        <AnimatePresence initial={false}>
          {messages.map((message) => (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, ease: EASE }}
            >
              <Message message={message} onShowDirections={onShowDirections} />
            </motion.div>
          ))}
        </AnimatePresence>
        {status === 'submitted' && (
          <div className="flex items-center gap-2 px-1 text-xs text-ink-muted">
            <FanMark className="size-4 animate-fan" />
            {t('thinking')}
          </div>
        )}
        {error && (
          <p className="rounded-xl bg-brick/10 px-3 py-2 text-sm">
            {error.message.includes('429') ? t('rateLimited') : t('error')}
          </p>
        )}
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-1.5">
        <div className="flex items-end gap-2 rounded-2xl bg-stone-raised/80 p-1.5 shadow-[inset_0_0_0_1px_var(--hairline)] focus-within:ring-2 focus-within:ring-route/40">
          <label htmlFor="assistant-input" className="sr-only">
            {t('placeholder')}
          </label>
          <textarea
            id="assistant-input"
            value={input}
            onChange={(e) => setInput(e.target.value.slice(0, MAX_CHARS))}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                ask(input);
              }
            }}
            rows={1}
            placeholder={t('placeholder')}
            className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-ink-muted"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => void stop()}
              aria-label={t('stop')}
              className="flex size-9 items-center justify-center rounded-xl bg-ink text-stone-raised"
            >
              <Square className="size-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              aria-label={t('send')}
              className="flex size-9 items-center justify-center rounded-xl bg-route text-white transition-opacity disabled:opacity-40"
            >
              <ArrowUp className="size-4.5" />
            </button>
          )}
        </div>
        <p className="px-1 text-[11px] leading-snug text-ink-muted">
          {t('notice')}
        </p>
      </form>
    </section>
  );
}

function Message({
  message,
  onShowDirections,
}: {
  message: UIMessage;
  onShowDirections: () => void;
}) {
  const t = useTranslations('Chat');
  const locale = useLocale();
  const user = message.role === 'user';
  return (
    <div className={user ? 'flex justify-end' : 'flex flex-col gap-2'}>
      {message.parts.map((part, i) => {
        if (part.type === 'text') {
          return user ? (
            <p
              key={i}
              className="max-w-[85%] rounded-2xl rounded-br-md bg-ink px-3 py-2 text-sm whitespace-pre-wrap text-stone-raised"
            >
              {part.text}
            </p>
          ) : (
            <div
              key={i}
              className="flex flex-col gap-1.5 px-1 text-sm leading-relaxed"
            >
              <RichText text={part.text} />
            </div>
          );
        }
        if (isToolUIPart(part) && getToolName(part) === 'get_route') {
          if (part.state !== 'output-available' || !isRouteOutput(part.output))
            return (
              <p key={i} className="px-1 text-xs text-ink-muted">
                {t('routing')}
              </p>
            );
          const { to, duration_min, length_m } = part.output;
          return (
            <button
              key={i}
              type="button"
              onClick={onShowDirections}
              className="flex items-center gap-3 rounded-2xl bg-route px-3 py-2.5 text-left text-white shadow-[0_8px_20px_-10px_var(--route)]"
            >
              <Footprints className="size-5 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-display text-md leading-tight font-semibold">
                  {locale === 'en' ? to.name_en : to.name_tr}
                </span>
                <span className="text-xs text-white/80">
                  {t('routeSummary', {
                    minutes: duration_min,
                    metres: length_m,
                  })}
                </span>
              </span>
              <span className="text-xs font-semibold">{t('showSteps')}</span>
            </button>
          );
        }
        if (isToolUIPart(part) && part.state !== 'output-available') {
          return (
            <p key={i} className="px-1 text-xs text-ink-muted">
              {getToolName(part) === 'search_knowledge'
                ? t('searching')
                : t('looking')}
            </p>
          );
        }
        return null;
      })}
    </div>
  );
}
