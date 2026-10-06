'use client';

import { Chat } from '@ai-sdk/react';
import { DefaultChatTransport, isToolUIPart, type UIMessage } from 'ai';

import { apiBaseUrl } from '@/lib/api/client';

/**
 * The chat outlives the panel: switching language remounts the whole map
 * (the locale is the root segment), so the conversation lives here, in the
 * module, and in sessionStorage for a full reload. A stream still running
 * during a soft switch carries on in the same `Chat`.
 */
const STORAGE_KEY = 'amap.chat.v1';
/** Enough for the visible thread; the API trims history further anyway. */
const KEEP_MESSAGES = 30;

let chat: Chat<UIMessage> | undefined;
let locale = 'tr';
/**
 * `get_route` calls already drawn on the map. Restored ones count as drawn:
 * coming back to the chat must not redraw an old answer over the route the
 * visitor has on screen now.
 */
const drawnRoutes = new Set<string>();

/** Language of the next request (read per request by the transport). */
export function setChatLocale(next: string) {
  locale = next;
}

export function campusChat(): Chat<UIMessage> {
  if (!chat) {
    const messages = readSaved();
    for (const message of messages)
      for (const part of message.parts)
        if (isToolUIPart(part)) drawnRoutes.add(part.toolCallId);
    chat = new Chat<UIMessage>({
      id: 'campus-assistant',
      messages,
      transport: new DefaultChatTransport({
        api: `${apiBaseUrl}/chat`,
        headers: () => ({ 'X-Amap-Locale': locale }),
      }),
    });
  }
  return chat;
}

/** True the first time a tool call is seen; later calls return false. */
export function claimRoute(toolCallId: string): boolean {
  if (drawnRoutes.has(toolCallId)) return false;
  drawnRoutes.add(toolCallId);
  return true;
}

export function saveChat(messages: UIMessage[]) {
  try {
    if (messages.length === 0) window.sessionStorage.removeItem(STORAGE_KEY);
    else
      window.sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(messages.slice(-KEEP_MESSAGES)),
      );
  } catch {
    // Storage may be full or blocked: the chat then lasts as long as the page.
  }
}

function readSaved(): UIMessage[] {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter(isMessage) : [];
  } catch {
    return [];
  }
}

function isMessage(value: unknown): value is UIMessage {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    'role' in value &&
    'parts' in value &&
    Array.isArray((value as { parts: unknown }).parts)
  );
}
