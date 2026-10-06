import { isToolUIPart, type ChatStatus, type UIMessage } from 'ai';

/**
 * Whether the assistant is working with nothing on screen to show for it:
 * before the first chunk, while the model reasons (reasoning is not shown),
 * and between a finished tool call and the first words of the answer. A
 * running tool shows its own line ("Finding the route…") instead.
 */
export function isThinking(
  messages: readonly UIMessage[],
  status: ChatStatus,
): boolean {
  if (status === 'submitted') return true;
  if (status !== 'streaming') return false;
  const last = messages[messages.length - 1];
  if (!last || last.role !== 'assistant') return true;
  const tail = last.parts[last.parts.length - 1];
  if (!tail) return true;
  if (tail.type === 'text') return tail.text.trim() === '';
  if (isToolUIPart(tail))
    return tail.state === 'output-available' || tail.state === 'output-error';
  return true;
}
