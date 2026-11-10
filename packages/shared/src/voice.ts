/**
 * Voice interaction state machine, shared by web and mobile.
 *
 * idle -> listening -> (transcribing) -> confirming -> idle
 *                   \-> error -> idle
 *
 * After recognition the transcript is always shown for confirmation when
 * confidence is low (plan section 8), so a noisy-field mishearing is never sent
 * silently.
 */

export type VoiceState =
  | { kind: "idle" }
  | { kind: "listening"; startedAt: number }
  | { kind: "transcribing" }
  | { kind: "confirming"; transcript: string; confidence: number }
  | { kind: "error"; reason: "unsupported" | "no-speech" | "denied" | "failed" };

export type VoiceEvent =
  | { type: "start"; at: number }
  | { type: "stop" }
  | { type: "cancel" }
  | { type: "result"; transcript: string; confidence: number }
  | { type: "fail"; reason: "unsupported" | "no-speech" | "denied" | "failed" }
  | { type: "accept" }
  | { type: "reset" };

export const CONFIRM_BELOW = 0.75;

export function voiceReducer(state: VoiceState, event: VoiceEvent): VoiceState {
  switch (event.type) {
    case "start":
      return { kind: "listening", startedAt: event.at };
    case "stop":
      return state.kind === "listening" ? { kind: "transcribing" } : state;
    case "cancel":
    case "reset":
    case "accept":
      return { kind: "idle" };
    case "result":
      if (!event.transcript.trim()) return { kind: "error", reason: "no-speech" };
      return { kind: "confirming", transcript: event.transcript.trim(), confidence: event.confidence };
    case "fail":
      return { kind: "error", reason: event.reason };
  }
}

/** Whether a recognised transcript can be sent without asking the user. */
export function canAutoSend(state: VoiceState): boolean {
  return state.kind === "confirming" && state.confidence >= CONFIRM_BELOW;
}
