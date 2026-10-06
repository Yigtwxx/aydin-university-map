import type { UIMessage } from 'ai';
import { describe, expect, it } from 'vitest';

import { isThinking } from './progress';

const user: UIMessage = {
  id: 'u1',
  role: 'user',
  parts: [{ type: 'text', text: 'Kütüphane kaç katlı?' }],
};
const reply = (...parts: unknown[]) =>
  [user, { id: 'a1', role: 'assistant', parts } as UIMessage] as const;
const tool = (state: string) => ({
  type: 'tool-search_knowledge',
  toolCallId: 'c1',
  state,
  input: { query: 'kütüphane', lang: 'tr' },
  ...(state === 'output-available' ? { output: [] } : {}),
});

describe('isThinking', () => {
  it('thinks until the first words arrive', () => {
    expect(isThinking([user], 'submitted')).toBe(true);
    expect(isThinking([user], 'streaming')).toBe(true);
    expect(
      isThinking(reply({ type: 'reasoning', text: '…' }), 'streaming'),
    ).toBe(true);
    expect(
      isThinking(reply({ type: 'text', text: 'Kütüphane' }), 'streaming'),
    ).toBe(false);
  });

  it('leaves a running tool its own line, then thinks again', () => {
    expect(isThinking(reply(tool('input-available')), 'streaming')).toBe(false);
    expect(isThinking(reply(tool('output-available')), 'streaming')).toBe(true);
  });

  it('is idle once the answer is done', () => {
    expect(
      isThinking(reply({ type: 'text', text: 'Yedi kat.' }), 'ready'),
    ).toBe(false);
    expect(isThinking([user], 'error')).toBe(false);
  });
});
