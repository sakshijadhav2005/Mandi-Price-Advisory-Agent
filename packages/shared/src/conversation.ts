/** Chat turns as shown on the Ask screen, shared by web and mobile. */

import type { ChatAnswer, ConversationDetail } from "./types";

export type Answer = Omit<ChatAnswer, "conversation_id" | "message_id">;

export type Turn =
  | { key: number; role: "user"; text: string }
  | { key: number; role: "assistant"; answer: Answer; messageId?: number };

let lastKey = 0;

/** Unique React key for a new turn. */
export function nextTurnKey(): number {
  return ++lastKey;
}

export function userTurn(text: string): Turn {
  return { key: nextTurnKey(), role: "user", text };
}

export function assistantTurn(answer: Answer, messageId?: number): Turn {
  return { key: nextTurnKey(), role: "assistant", answer, messageId };
}

/** Turns for a saved conversation (from History). */
export function turnsFromConversation(c: ConversationDetail): Turn[] {
  return c.messages.map((m) => (m.role === "assistant" && m.answer ? assistantTurn(m.answer, m.id) : userTurn(m.text)));
}
