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

/**
 * Why voice input stopped. "insecure" means the page is not served over https
 * (or localhost), so the browser refuses microphone access.
 */
export type VoiceFailure = "unsupported" | "insecure" | "no-speech" | "denied" | "no-mic" | "network" | "failed";

export type VoiceState =
  | { kind: "idle" }
  | { kind: "listening"; startedAt: number }
  | { kind: "transcribing" }
  | { kind: "confirming"; transcript: string; confidence: number }
  | { kind: "error"; reason: VoiceFailure };

export type VoiceEvent =
  | { type: "start"; at: number }
  | { type: "stop" }
  | { type: "cancel" }
  | { type: "result"; transcript: string; confidence: number }
  | { type: "fail"; reason: VoiceFailure }
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
