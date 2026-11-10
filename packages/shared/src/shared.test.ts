import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, MemoryStore, canAutoSend, formatRupees, voiceReducer } from "./index";

describe("formatRupees", () => {
  it("uses Indian grouping", () => {
    expect(formatRupees(123456)).toBe("1,23,456");
    expect(formatRupees(2715.4, "mr")).toBe("2,715");
    expect(formatRupees(null)).toBe("–");
  });
});

describe("voiceReducer", () => {
  it("asks for confirmation when confidence is low", () => {
    let s = voiceReducer({ kind: "idle" }, { type: "start", at: 0 });
    expect(s.kind).toBe("listening");
    s = voiceReducer(s, { type: "result", transcript: " कांदा विकू ", confidence: 0.4 });
    expect(s).toEqual({ kind: "confirming", transcript: "कांदा विकू", confidence: 0.4 });
    expect(canAutoSend(s)).toBe(false);
    expect(canAutoSend({ kind: "confirming", transcript: "x", confidence: 0.9 })).toBe(true);
  });

  it("treats empty transcripts as no speech", () => {
    expect(voiceReducer({ kind: "listening", startedAt: 0 }, { type: "result", transcript: "  ", confidence: 1 })).toEqual({
      kind: "error",
      reason: "no-speech",
    });
  });
});

describe("ApiClient", () => {
  it("sends a stable guest id and parses errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Login required" }), { status: 401 }));
    const api = new ApiClient("http://x", new MemoryStore(), fetchMock as unknown as typeof fetch);
    await expect(api.meta()).rejects.toEqual(new ApiError(401, "Login required"));
    const first = fetchMock.mock.calls[0][1].headers["X-Guest-Id"];
    await api.meta().catch(() => undefined);
    expect(fetchMock.mock.calls[1][1].headers["X-Guest-Id"]).toBe(first);
  });

  it("uses the bearer token after login", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: "tok", user: { id: 1, phone: "+91", language: "hi" } })))
      .mockResolvedValueOnce(new Response(JSON.stringify([])));
    const api = new ApiClient("http://x/", new MemoryStore(), fetchMock as unknown as typeof fetch);
    await api.verifyOtp("9876543210", "123456");
    await api.conversations();
    expect(fetchMock.mock.calls[1][0]).toBe("http://x/conversations");
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer tok");
  });
});
