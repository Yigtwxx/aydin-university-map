import type { UIMessage } from 'ai';
import { describe, expect, it } from 'vitest';

import { sourcesOf } from './sources';

function answer(parts: unknown[]): UIMessage {
  return { id: 'a1', role: 'assistant', parts } as UIMessage;
}

let calls = 0;
const search = (output: unknown, state = 'output-available') => ({
  type: 'tool-search_knowledge',
  toolCallId: `call-${(calls += 1)}`,
  state,
  input: { query: 'kütüphane', lang: 'tr' },
  output,
});

describe('sourcesOf', () => {
  it('lists the passages a knowledge search returned, once per title', () => {
    const message = answer([
      search([
        { title: 'Kütüphane', node_id: 'scene_1', score: 0.8 },
        { title: 'T Blok Bahçe', node_id: null, score: 0.7 },
        { title: 'Kütüphane', node_id: 'scene_2', score: 0.6 },
      ]),
      { type: 'text', text: 'Kütüphane dört katlı.' },
    ]);
    expect(sourcesOf(message)).toEqual([
      { title: 'Kütüphane', nodeId: 'scene_1' },
      { title: 'T Blok Bahçe', nodeId: undefined },
    ]);
  });

  it('ignores failed or unfinished searches and other tools', () => {
    const message = answer([
      search([{ error: 'knowledge search is unavailable right now' }]),
      search(undefined, 'input-available'),
      {
        type: 'tool-get_route',
        toolCallId: 'r1',
        state: 'output-available',
        input: {},
        output: { title: 'not a source' },
      },
    ]);
    expect(sourcesOf(message)).toEqual([]);
  });

  it('keeps the row short', () => {
    const hits = ['A', 'B', 'C', 'D', 'E', 'F'].map((t) => ({ title: t }));
    expect(sourcesOf(answer([search(hits)]))).toHaveLength(4);
  });
});
