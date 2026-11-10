import type {
  AppNotification,
  ChatAnswer,
  ChatRequest,
  ConversationDetail,
  ConversationSummary,
  Meta,
  PriceAlert,
  PricesResponse,
  Transcript,
} from "./types";

/** Key-value storage; localStorage on web, AsyncStorage-backed adapter on React Native. */
export interface KeyValueStore {
  get(key: string): string | null;
  set(key: string, value: string): void;
  remove(key: string): void;
}

export class MemoryStore implements KeyValueStore {
  private data = new Map<string, string>();
  get(key: string) {
    return this.data.get(key) ?? null;
  }
  set(key: string, value: string) {
    this.data.set(key, value);
  }
  remove(key: string) {
    this.data.delete(key);
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "mandi.token";
const GUEST_KEY = "mandi.guestId";

function randomId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID();
  return "g-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export class ApiClient {
  constructor(
    public baseUrl: string,
    private store: KeyValueStore,
    private fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  get token(): string | null {
    return this.store.get(TOKEN_KEY);
  }

  setToken(token: string | null) {
    if (token) this.store.set(TOKEN_KEY, token);
    else this.store.remove(TOKEN_KEY);
  }

  guestId(): string {
    let id = this.store.get(GUEST_KEY);
    if (!id) {
      id = randomId();
      this.store.set(GUEST_KEY, id);
    }
    return id;
  }

  authHeaders(): Record<string, string> {
    const token = this.token;
    return token ? { Authorization: `Bearer ${token}` } : { "X-Guest-Id": this.guestId() };
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = { ...this.authHeaders(), ...(init.headers as Record<string, string>) };
    if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const res = await this.fetchImpl(this.baseUrl.replace(/\/$/, "") + path, { ...init, headers });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  }

  meta() {
    return this.request<Meta>("/meta");
  }

  chat(body: ChatRequest) {
    return this.request<ChatAnswer>("/chat", { method: "POST", body: JSON.stringify(body) });
  }

  prices(crop: string, days = 30, district?: string | null) {
    const d = district ? `&district=${encodeURIComponent(district)}` : "";
    return this.request<PricesResponse>(`/prices?crop=${encodeURIComponent(crop)}&days=${days}${d}`);
  }

  conversations() {
    return this.request<ConversationSummary[]>("/conversations");
  }

  conversation(id: number) {
    return this.request<ConversationDetail>(`/conversations/${id}`);
  }

  deleteConversation(id: number) {
    return this.request<{ deleted: boolean }>(`/conversations/${id}`, { method: "DELETE" });
  }

  feedback(messageId: number, helpful: boolean, comment = "") {
    return this.request<{ saved: boolean }>("/feedback", {
      method: "POST",
      body: JSON.stringify({ message_id: messageId, helpful, comment }),
    });
  }

  alerts() {
    return this.request<PriceAlert[]>("/alerts");
  }

  createAlert(alert: {
    crop: string;
    market: string | null;
    district?: string | null;
    direction: "above" | "below";
    threshold: number;
    language: string;
  }) {
    return this.request<PriceAlert>("/alerts", { method: "POST", body: JSON.stringify(alert) });
  }

  deleteAlert(id: number) {
    return this.request<{ deleted: boolean }>(`/alerts/${id}`, { method: "DELETE" });
  }

  notifications(unreadOnly = false) {
    return this.request<AppNotification[]>(`/alerts/notifications${unreadOnly ? "?unread_only=true" : ""}`);
  }

  markNotificationsRead() {
    return this.request<{ ok: boolean }>("/alerts/notifications/read", { method: "POST" });
  }

  registerDevice(pushToken: string, platform: "android" | "ios" | "web" | "unknown", language: string) {
    return this.request<{ registered: boolean }>("/devices", {
      method: "POST",
      body: JSON.stringify({ push_token: pushToken, platform, language }),
    });
  }

  requestOtp(phone: string) {
    return this.request<{ sent: boolean; dev_code?: string }>("/auth/otp/request", {
      method: "POST",
      body: JSON.stringify({ phone }),
    });
  }

  async verifyOtp(phone: string, code: string, language?: string) {
    const res = await this.request<{ token: string; user: { id: number; phone: string; language: string } }>(
      "/auth/otp/verify",
      { method: "POST", body: JSON.stringify({ phone, code, language }) },
    );
    this.setToken(res.token);
    return res.user;
  }

  transcribe(audio: Blob, language?: string, filename = "speech.webm") {
    const form = new FormData();
    form.append("audio", audio, filename);
    if (language) form.append("language", language);
    return this.request<Transcript>("/voice/transcribe", { method: "POST", body: form });
  }

  async speak(text: string, language: string): Promise<Blob> {
    const res = await this.fetchImpl(this.baseUrl.replace(/\/$/, "") + "/voice/speak", {
      method: "POST",
      headers: { ...this.authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  }
}
