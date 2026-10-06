import { getToolName, isToolUIPart, type UIMessage } from 'ai';

export interface Source {
  title: string;
  /** The 360° spot the passage describes, when it has one. */
  nodeId?: string;
}

const MAX_SOURCES = 4;

interface KnowledgeHit {
  title?: unknown;
  node_id?: unknown;
  error?: unknown;
}

/**
 * What an answer was grounded on: the passages its `search_knowledge` calls
 * returned (the stream carries no per-sentence citations), one per title,
 * in the order they came. Failed searches add nothing.
 */
export function sourcesOf(message: UIMessage): Source[] {
  const seen = new Map<string, Source>();
  for (const part of message.parts) {
    if (
      !isToolUIPart(part) ||
      getToolName(part) !== 'search_knowledge' ||
      part.state !== 'output-available' ||
      !Array.isArray(part.output)
    )
      continue;
    for (const hit of part.output as KnowledgeHit[]) {
      if (typeof hit?.title !== 'string' || !hit.title.trim() || hit.error)
        continue;
      const title = hit.title.trim();
      const known = seen.get(title);
      const nodeId = typeof hit.node_id === 'string' ? hit.node_id : undefined;
      if (!known) seen.set(title, { title, nodeId });
      else if (!known.nodeId && nodeId) known.nodeId = nodeId;
    }
  }
  return [...seen.values()].slice(0, MAX_SOURCES);
}
