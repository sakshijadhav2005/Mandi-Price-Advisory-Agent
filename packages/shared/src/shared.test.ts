import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, MemoryStore, canAutoSend, formatRupees, turnsFromConversation, userTurn, voiceReducer, type Answer } from "./index";

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

describe("conversation turns", () => {
  it("maps a saved conversation to turns with unique keys", () => {
    const answer = { text: "Sell now", language: "en" } as unknown as Answer;
    const turns = turnsFromConversation({
      id: 1,
      title: "onion",
      language: "en",
      messages: [
        { id: 10, role: "user", text: "Sell onion?", language: "en", created_at: "" },
        { id: 11, role: "assistant", text: "Sell now", language: "en", created_at: "", answer },
        { id: 12, role: "assistant", text: "orphan", language: "en", created_at: "" },
      ],
    });
    expect(turns.map((t) => t.role)).toEqual(["user", "assistant", "user"]);
    expect(turns[1]).toMatchObject({ role: "assistant", messageId: 11, answer });
    expect(new Set(turns.map((t) => t.key)).size).toBe(3);
    expect(userTurn("x").key).toBeGreaterThan(turns[2].key);
  });
});

describe("marketOnDay", () => {
  const market = {
    market: "pune",
    market_name: "Pune",
    names: {},
    status: "fresh" as const,
    age_days: 0,
    latest: { date: "2026-11-23", min: 1, modal: 300, max: 3 },
    source: "agmarknet_csv",
    history: [
      { date: "2026-11-18", min: 1, modal: 100, max: 3 },
      { date: "2026-11-20", min: 1, modal: 200, max: 3 },
      { date: "2026-11-23", min: 1, modal: 300, max: 3 },
    ],
  };
  it("shows the chosen day's price, else the last one before it", async () => {
    const { marketOnDay, daysBefore } = await import("./index");
    expect(marketOnDay(market, "2026-11-23", "2026-11-23", 3).point?.modal).toBe(300);
    expect(marketOnDay(market, "2026-11-20", "2026-11-23", 3)).toMatchObject({ point: { modal: 200 }, ageDays: 0, status: "fresh" });
    expect(marketOnDay(market, "2026-11-22", "2026-11-23", 3)).toMatchObject({ point: { modal: 200 }, ageDays: 2 });
    expect(marketOnDay(market, "2026-11-17", "2026-11-23", 3)).toEqual({ point: null, status: "missing", ageDays: null });
    expect(daysBefore("2026-12-03", 6)).toBe("2026-11-27");
    expect(daysBefore("2026-03-01", 1)).toBe("2026-02-28");
  });
});
