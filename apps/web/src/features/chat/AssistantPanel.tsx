'use client';

import { useChat } from '@ai-sdk/react';
import { getToolName, isToolUIPart, type UIMessage } from 'ai';
import { cn } from 'cn';
import {
  ArrowUp,
  BookOpen,
  CircleAlert,
  DoorOpen,
  Footprints,
  Square,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useLocale, useTranslations } from 'next-intl';
import { type FormEvent, useEffect, useRef, useState } from 'react';

import { RouteMark } from '@/components/brand/RouteMark';
import { useCampusGraph } from '@/features/campus/queries';
import { RichText } from '@/features/chat/RichText';
import { CHIP_COLORS } from '@/features/route/placeIcons';
import { useRouteStore } from '@/features/route/store';

import { isThinking } from './progress';
import { campusChat, claimRoute, saveChat, setChatLocale } from './session';
import { sourcesOf } from './sources';

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
  // One conversation per tab, kept outside the panel (see ./session): it
  // survives the remount a language switch causes.
  const [chat] = useState(campusChat);
  const { messages, sendMessage, status, error, stop } = useChat({ chat });
  const [input, setInput] = useState('');
  const scroller = useRef<HTMLDivElement>(null);
  const busy = status === 'submitted' || status === 'streaming';

  useEffect(() => setChatLocale(locale), [locale]);
  // Saved between turns, not on every streamed token.
  useEffect(() => {
    if (status === 'ready' || status === 'error') saveChat(messages);
  }, [messages, status]);

  // A finished get_route call fills the directions, so the map draws it.
  useEffect(() => {
    for (const message of messages) {
      for (const part of message.parts) {
        if (
          isToolUIPart(part) &&
          getToolName(part) === 'get_route' &&
          part.state === 'output-available' &&
          isRouteOutput(part.output) &&
          claimRoute(part.toolCallId)
        ) {
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

  // Follows the answer as it streams; a restored chat opens at its end.
  const scrolled = useRef(false);
  useEffect(() => {
    scroller.current?.scrollTo({
      top: scroller.current.scrollHeight,
      behavior: scrolled.current ? 'smooth' : 'auto',
    });
    scrolled.current = true;
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

  // Each suggestion wears the badge of the place it asks about, in the
  // colours the directions tab gives those places.
  const suggestions = [
    {
      text: t('suggest1'),
      badge: <span className="text-[11px] font-semibold">A</span>,
      tone: { bg: 'var(--block-main)', fg: 'var(--block-ink)' },
    },
    {
      text: t('suggest2'),
      badge: <BookOpen className="size-3.5" strokeWidth={2.25} />,
      tone: CHIP_COLORS.library,
    },
    {
      text: t('suggest3'),
      badge: <DoorOpen className="size-3.5" strokeWidth={2.25} />,
      tone: CHIP_COLORS.outdoor,
    },
  ];

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
          <div className="flex flex-col gap-3.5 pt-0.5">
            <div className="px-0.5">
              <p
                aria-hidden
                className="text-md leading-tight font-semibold tracking-heading"
              >
                {t('title')}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-ink-muted">
                {t('intro')}
              </p>
            </div>
            <ul className="flex flex-col divide-y divide-hairline overflow-hidden rounded-card bg-fill">
              {suggestions.map((s) => (
                <li key={s.text}>
                  <button
                    type="button"
                    onClick={() => ask(s.text)}
                    className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors duration-150 ease-out-soft hover:bg-fill-strong focus-visible:-outline-offset-2"
                  >
                    <span
                      aria-hidden
                      style={{ backgroundColor: s.tone.bg, color: s.tone.fg }}
                      className="flex size-6 shrink-0 items-center justify-center rounded-[7px]"
                    >
                      {s.badge}
                    </span>
                    {s.text}
                  </button>
                </li>
              ))}
            </ul>
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
        {/* Also while it reasons and after a tool, until the words come:
            Groq then writes the whole answer in a fraction of a second. */}
        {isThinking(messages, status) && (
          <div className="flex items-center gap-2 px-0.5 text-xs text-ink-muted">
            <RouteMark className="size-4 animate-mark" />
            {t('thinking')}
          </div>
        )}
        {error && (
          <p className="flex items-start gap-2 rounded-control bg-brick/10 px-3 py-2 text-sm">
            <CircleAlert
              className="mt-px size-4 shrink-0 text-brick"
              aria-hidden
            />
            {error.message.includes('429') ? t('rateLimited') : t('error')}
          </p>
        )}
      </div>

      <form onSubmit={onSubmit}>
        <div className="flex items-end gap-1.5 rounded-card bg-fill p-1 transition-[background-color,box-shadow] duration-150 ease-out-soft focus-within:bg-stone-raised focus-within:shadow-thumb focus-within:ring-2 focus-within:ring-route/40">
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
            // 16 px on touch screens stops iOS zooming into the field on focus.
            className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2.5 py-2 text-[16px] leading-5 outline-none placeholder:text-ink-muted md:text-md"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => void stop()}
              aria-label={t('stop')}
              className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-ink text-stone-raised"
            >
              <Square className="size-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              aria-label={t('send')}
              className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-route text-on-route transition-colors duration-150 ease-out-soft disabled:bg-fill-strong disabled:text-ink-faint"
            >
              <ArrowUp className="size-4" strokeWidth={2.25} />
            </button>
          )}
        </div>
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
  const sources = user ? [] : sourcesOf(message);
  return (
    <div className={user ? 'flex justify-end' : 'flex flex-col gap-2'}>
      {!user && (
        <span
          aria-hidden
          className="flex items-center gap-2 px-0.5 text-xs font-medium text-ink-muted"
        >
          <AssistantMark className="size-5 rounded-[6px] [&_svg]:size-3.5" />
          {t('title')}
        </span>
      )}
      {message.parts.map((part, i) => {
        if (part.type === 'text') {
          return user ? (
            <p
              key={i}
              className="max-w-[85%] rounded-[16px] rounded-br-[6px] bg-ink px-3 py-2 text-sm whitespace-pre-wrap text-stone-raised"
            >
              {part.text}
            </p>
          ) : (
            <div
              key={i}
              className="flex flex-col gap-2 px-0.5 text-sm leading-relaxed [&_strong]:font-semibold"
            >
              <RichText text={part.text} newTab={t('newTab')} />
            </div>
          );
        }
        if (isToolUIPart(part) && getToolName(part) === 'get_route') {
          if (part.state !== 'output-available' || !isRouteOutput(part.output))
            return (
              <p key={i} className="px-0.5 text-xs text-ink-muted">
                {t('routing')}
              </p>
            );
          const { to, duration_min, length_m } = part.output;
          return (
            <button
              key={i}
              type="button"
              onClick={onShowDirections}
              className="flex items-center gap-3 rounded-card bg-stone-raised/80 p-2 pr-3 text-left shadow-[inset_0_0_0_1px_var(--hairline)] transition-colors duration-150 ease-out-soft hover:bg-stone-raised"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-route text-on-route">
                <Footprints className="size-4.5" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-md leading-tight font-medium tracking-heading">
                  {locale === 'en' ? to.name_en : to.name_tr}
                </span>
                <span className="tabular text-xs text-ink-muted">
                  {t('routeSummary', {
                    minutes: duration_min,
                    metres: length_m,
                  })}
                </span>
              </span>
              <span className="text-xs font-medium text-route">
                {t('showSteps')}
              </span>
            </button>
          );
        }
        if (isToolUIPart(part) && part.state !== 'output-available') {
          return (
            <p key={i} className="px-0.5 text-xs text-ink-muted">
              {getToolName(part) === 'search_knowledge'
                ? t('searching')
                : t('looking')}
            </p>
          );
        }
        return null;
      })}
      {sources.length > 0 && <Sources sources={sources} />}
    </div>
  );
}

/**
 * What the answer was grounded on, one quiet row. A passage about a 360°
 * spot opens that spot, so the visitor can check it with their own eyes.
 */
function Sources({ sources }: { sources: ReturnType<typeof sourcesOf> }) {
  const t = useTranslations('Chat');
  const graph = useCampusGraph();
  const setExploreNode = useRouteStore((s) => s.setExploreNode);
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-0.5 pt-0.5">
      <span className="flex items-center gap-1 text-2xs font-medium text-ink-muted">
        <BookOpen className="size-3" aria-hidden />
        {t('sources')}
      </span>
      <ul className="contents">
        {sources.map((source) => {
          const spot =
            source.nodeId && graph.data?.byId.has(source.nodeId)
              ? source.nodeId
              : undefined;
          const chip =
            'flex h-6 max-w-[12rem] items-center gap-1 rounded-full bg-fill px-2 text-2xs font-medium text-ink';
          return (
            <li key={source.title} className="min-w-0">
              {spot ? (
                <button
                  type="button"
                  onClick={() => setExploreNode(spot)}
                  title={t('openSource', { title: source.title })}
                  aria-label={t('openSource', { title: source.title })}
                  className={`${chip} transition-colors duration-150 ease-out-soft hover:bg-fill-strong`}
                >
                  <span className="truncate">{source.title}</span>
                  <span
                    aria-hidden
                    className="shrink-0 text-[9px] font-semibold text-ink-muted"
                  >
                    360°
                  </span>
                </button>
              ) : (
                <span className={chip}>
                  <span className="truncate">{source.title}</span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** The assistant's face: the logomark on an ink tile, as in the brand row. */
function AssistantMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'flex shrink-0 items-center justify-center bg-ink text-stone-raised shadow-thumb [--mark-accent:var(--ice-inverse)]',
        className,
      )}
    >
      <RouteMark />
    </span>
  );
}
