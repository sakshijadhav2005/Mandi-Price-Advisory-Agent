import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import "./i18n";
import { AppProvider } from "./lib/app-context";

const meta = {
  today: "2026-11-08",
  district: { name: "Nashik", state: "Maharashtra" },
  languages: { en: "English", hi: "Hindi", mr: "Marathi" },
  crops: [
    { id: "onion", name: "Onion", names: { hi: "प्याज", mr: "कांदा" } },
    { id: "tomato", name: "Tomato", names: { hi: "टमाटर", mr: "टोमॅटो" } },
  ],
  markets: [{ id: "nashik", name: "Nashik", names: { mr: "नाशिक" }, lat: 20, lon: 73.8 }],
  voice: { server_stt: false, server_tts: false },
  auth_required: false,
  stale_after_days: 3,
};

const answer = {
  conversation_id: 1,
  message_id: 2,
  text: "आता विका. खात्री: जास्त.",
  language: "mr",
  decision: "sell",
  confidence: "high",
  recommendation: {
    crop: "onion",
    decision: "sell",
    confidence: "high",
    horizon_days: 7,
    best_market_now: "nashik",
    best_net_now_per_qtl: 2638,
    best_market_hold: "nashik",
    best_net_hold_per_qtl: 2500,
    uncertainty_per_qtl: 200,
    markets: [],
    reason_codes: [],
  },
  sources: [{ id: "price:onion:nashik:2026-11-07", kind: "price", crop: "onion", market: "nashik", market_name: "Nashik", date: "2026-11-07", origin: "synthetic" }],
  disclaimer: "हा फक्त निर्णयासाठी मदत करणारा सल्ला आहे.",
  mode: "offline",
  trace: [{ tool: "compute_recommendation", args: {}, is_error: false, summary: "sell (high)" }],
  warnings: [],
  latency_ms: 20,
};

function renderApp() {
  return render(
    <MemoryRouter>
      <AppProvider>
        <App />
      </AppProvider>
    </MemoryRouter>,
  );
}

describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const body = url.endsWith("/meta") ? meta : answer;
        return new Response(JSON.stringify(body), { status: 200 });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("asks for a language first, then answers in Marathi with a decision card", async () => {
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /मराठी/ }));
    const box = await screen.findByPlaceholderText(/तुमचा प्रश्न लिहा/);
    expect(screen.queryByText("तुमची भाषा निवडा")).toBeNull();
    // Header and tab bar switch language too (regression: they stayed in English).
    expect(screen.getByRole("heading", { name: "मंडी सल्लागार" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /दर/ })).toBeInTheDocument();
    fireEvent.change(box, { target: { value: "कांदा विकू का?" } });
    fireEvent.click(screen.getByRole("button", { name: "पाठवा" }));
    expect(await screen.findByText("आता विका. खात्री: जास्त.")).toBeInTheDocument();
    expect(screen.getAllByText("आता विका").length).toBeGreaterThan(0);
    expect(screen.getByText(/2,638/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "स्रोत आणि तपशील पाहा" }));
    await waitFor(() => expect(screen.getByText(/compute_recommendation/)).toBeInTheDocument());
    const chatCall = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(([u]) => String(u).endsWith("/chat"));
    expect(JSON.parse(chatCall![1].body).language).toBe("mr");
  });
});
