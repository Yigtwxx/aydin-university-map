import { Fragment, type ReactNode } from 'react';

const BOLD = /\*\*(.+?)\*\*/g;
const LIST_ITEM = /^\s*(?:[-•*]|\d+[.)])\s+/;

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(BOLD)) {
    const at = match.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push(<strong key={at}>{match[1]}</strong>);
    last = at + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * The few formats models still use despite the prompt: paragraphs, "- " and
 * "1." lists, **bold**. Rendered as React nodes, never as HTML.
 */
export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length === 0) return;
    blocks.push(
      <ul key={`l${blocks.length}`} className="ml-4 list-disc space-y-0.5">
        {list.map((item, i) => (
          <li key={i}>{inline(item)}</li>
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
      blocks.push(<p key={`p${blocks.length}`}>{inline(trimmed)}</p>);
  }
  flush();
  return <Fragment>{blocks}</Fragment>;
}
