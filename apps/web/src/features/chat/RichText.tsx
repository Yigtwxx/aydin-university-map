import { Fragment, type ReactNode } from 'react';

const BOLD = /\*\*(.+?)\*\*/g;
const LIST_ITEM = /^\s*(?:[-•*]|\d+[.)])\s+/;
/**
 * Addresses in an answer: e-mail first (so "info@aydin.edu.tr" is not read as
 * a bare host), then http(s) links, then bare `www.` hosts and the
 * university's own `aydin.edu.tr` addresses. A link stops at a space, a
 * quote or an apostrophe ("aydin.edu.tr’den").
 */
const LINK =
  /([\w.+-]+@[\w-]+(?:\.[\w-]+)+)|(\bhttps?:\/\/[^\s<>"'’)\]]+)|(\b(?:www\.[\w-]+(?:\.[\w-]+)+|(?:[\w-]+\.)*aydin\.edu\.tr)(?:\/[^\s<>"'’)\]]*)?)/gi;
/** Sentence punctuation that ends a sentence, not the address. */
const TRAILING = /[.,;:!?]+$/;
/** Shown text: no scheme or `www.`; CSS ellipsizes what is still too long. */
const SHOWN_PREFIX = /^(?:https?:\/\/)?(?:www\.)?/i;

export interface LinkPart {
  href: string;
  text: string;
}

/** Splits `text` into plain strings and links (only http(s) and mailto). */
export function linkify(text: string): (string | LinkPart)[] {
  const out: (string | LinkPart)[] = [];
  let last = 0;
  for (const match of text.matchAll(LINK)) {
    const at = match.index ?? 0;
    const [raw = '', email, url] = match;
    const address = raw.replace(TRAILING, '');
    if (!address) continue;
    if (at > last) out.push(text.slice(last, at));
    const href = email
      ? `mailto:${address}`
      : url
        ? address
        : `https://${address}`;
    const shown = email ? address : address.replace(SHOWN_PREFIX, '');
    out.push({ href, text: shown.replace(/\/$/, '') });
    last = at + address.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

interface Options {
  /** Screen-reader note after each link, e.g. "(opens in a new tab)". */
  newTab?: string;
}

function links(text: string, key: string, options: Options): ReactNode[] {
  return linkify(text).map((part, i) =>
    typeof part === 'string' ? (
      part
    ) : (
      <a
        key={`${key}-${i}`}
        href={part.href}
        target="_blank"
        rel="noopener noreferrer"
        title={part.href.replace(/^mailto:/, '')}
        className="inline-block max-w-full truncate align-bottom font-medium text-route underline decoration-route/35 underline-offset-2 transition-colors duration-150 ease-out-soft hover:decoration-route"
      >
        {part.text}
        {options.newTab && <span className="sr-only"> {options.newTab}</span>}
      </a>
    ),
  );
}

function inline(text: string, options: Options): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(BOLD)) {
    const at = match.index ?? 0;
    if (at > last) out.push(...links(text.slice(last, at), `t${at}`, options));
    out.push(
      <strong key={at}>{links(match[1] ?? '', `b${at}`, options)}</strong>,
    );
    last = at + match[0].length;
  }
  if (last < text.length)
    out.push(...links(text.slice(last), `t${last}`, options));
  return out;
}

/**
 * The few formats models still use despite the prompt: paragraphs, "- " and
 * "1." lists, **bold**, plus clickable web and e-mail addresses. Rendered as
 * React nodes, never as HTML.
 */
export function RichText({ text, newTab }: { text: string } & Options) {
  const options = { newTab };
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length === 0) return;
    blocks.push(
      <ul
        key={`l${blocks.length}`}
        className="ml-4 list-disc space-y-1 marker:text-ink-faint"
      >
        {list.map((item, i) => (
          <li key={i}>{inline(item, options)}</li>
        ))}
      </ul>,
    );
    list = [];
  };
  for (const line of text.split('\n')) {
    if (LIST_ITEM.test(line)) {
      list.push(line.replace(LIST_ITEM, ''));
      continue;
    }
    flush();
    const trimmed = line.trim().replace(/^#+\s*/, '');
    if (trimmed)
      blocks.push(<p key={`p${blocks.length}`}>{inline(trimmed, options)}</p>);
  }
  flush();
  return <Fragment>{blocks}</Fragment>;
}
