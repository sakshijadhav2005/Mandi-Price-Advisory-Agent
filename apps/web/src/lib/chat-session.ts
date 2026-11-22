import type { Turn } from "@mandi/shared";
import { useSyncExternalStore } from "react";

/**
 * The current conversation on the Ask page, kept outside the page so it survives switching
 * tabs: a question still being answered when the farmer opens Prices or History finishes
 * in the background and is there on coming back.
 *
 * `session` changes on "new chat" and logout, so an answer that arrives afterwards is
 * dropped instead of landing in the wrong conversation.
 */
export interface ChatSession {
  session: number;
  conversationId: number | null;
  turns: Turn[];
  busy: boolean;
  error: string | null;
  crop: string;
  qty: string;
}

const initial = (session: number): ChatSession => ({ session, conversationId: null, turns: [], busy: false, error: null, crop: "", qty: "" });

let state: ChatSession = initial(0);
const listeners = new Set<() => void>();

export function getChat(): ChatSession {
  return state;
}

export function setChat(patch: Partial<ChatSession> | ((s: ChatSession) => Partial<ChatSession>)): void {
  state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
  listeners.forEach((l) => l());
}

/** Start a new, empty conversation (keeps the chosen crop and quantity unless `all`). */
export function resetChat(all = false): void {
  const { crop, qty } = state;
  setChat({ ...initial(state.session + 1), ...(all ? {} : { crop, qty }) });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useChat(): ChatSession {
  return useSyncExternalStore(subscribe, getChat, getChat);
}
