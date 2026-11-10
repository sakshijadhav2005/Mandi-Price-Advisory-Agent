/** Types mirroring the FastAPI responses (backend/app/api). */

export type Decision = "sell" | "hold" | "insufficient_data";
export type Confidence = "high" | "medium" | "low";
export type MarketStatus = "fresh" | "stale" | "missing" | "sparse";

export interface MarketAssessment {
  market: string;
  latest_date: string | null;
  age_days: number | null;
  points: number;
  status: MarketStatus;
  modal_latest: number | null;
  min_latest: number | null;
  max_latest: number | null;
  avg_7d: number | null;
  distance_km: number | null;
  transport_per_qtl: number | null;
  net_now_per_qtl: number | null;
  trend_pct_per_day: number | null;
  seasonal_pct?: number | null;
  expected_price_after_hold: number | null;
  net_hold_per_qtl: number | null;
  source: string | null;
}

export interface Recommendation {
  crop: string;
  as_of: string;
  decision: Decision;
  confidence: Confidence;
  horizon_days: number;
  quantity_qtl: number | null;
  best_market_now: string | null;
  best_net_now_per_qtl: number | null;
  best_market_hold: string | null;
  best_net_hold_per_qtl: number | null;
  expected_gain_per_qtl: number | null;
  expected_gain_pct: number | null;
  uncertainty_per_qtl: number | null;
  total_value_now: number | null;
  reason_codes: string[];
  markets: MarketAssessment[];
  assumptions: Record<string, unknown>;
}

export interface PriceSource {
  id: string;
  kind: "price";
  crop: string;
  market: string;
  market_name: string;
  date: string;
  origin: string;
}

export interface AdvisorySource {
  id: string;
  kind: "advisory";
  title: string;
  language: string;
  published: string;
  origin: string;
  excerpt: string;
}

export type Source = PriceSource | AdvisorySource;

export interface TraceStep {
  tool: string;
  args: Record<string, unknown>;
  is_error: boolean;
  summary: string;
}

export interface ChatAnswer {
  conversation_id: number;
  message_id: number;
  text: string;
  language: string;
  decision: Decision | null;
  confidence: Confidence | null;
  recommendation: Recommendation | null;
  sources: Source[];
  disclaimer: string;
  mode: "llm" | "offline";
  trace: TraceStep[];
  warnings: string[];
  latency_ms: number;
}

export interface ChatRequest {
  message: string;
  language: string;
  crop?: string | null;
  quantity_qtl?: number | null;
  lat?: number | null;
  lon?: number | null;
  conversation_id?: number | null;
  input_mode?: "text" | "voice";
  district?: string | null;
}

export interface Named {
  id: string;
  name: string;
  names: Record<string, string>;
}

export interface LanguagePackInfo {
  code: string;
  name: string;
  speech_locale: string;
}

export interface PriceAlert {
  id: number;
  crop: string;
  market: string | null;
  district?: string | null;
  direction: "above" | "below";
  threshold: number;
  language: string;
  active: boolean;
  last_triggered_on: string | null;
}

export interface AppNotification {
  id: number;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
}

export interface DistrictInfo extends Named {
  state: string;
  centre: { lat: number; lon: number };
  markets: string[];
}

export interface Meta {
  today: string;
  districts?: DistrictInfo[];
  language_packs?: LanguagePackInfo[];
  district: { name: string; state: string };
  languages: Record<string, string>;
  crops: Named[];
  markets: (Named & { lat: number; lon: number; district?: string })[];
  voice: { server_stt: boolean; server_tts: boolean };
  auth_required: boolean;
  stale_after_days: number;
}

export interface PricePointDto {
  date: string;
  min: number;
  modal: number;
  max: number;
}

export interface MarketPrices {
  market: string;
  market_name: string;
  names: Record<string, string>;
  status: MarketStatus;
  age_days: number | null;
  latest: PricePointDto | null;
  source: string | null;
  history: PricePointDto[];
}

export interface PricesResponse {
  crop: string;
  district?: string;
  unit: string;
  as_of: string;
  stale_after_days: number;
  markets: MarketPrices[];
}

export interface ConversationSummary {
  id: number;
  title: string;
  language: string;
  created_at: string;
  messages: number;
}

export interface ConversationMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  language: string;
  created_at: string;
  answer?: Omit<ChatAnswer, "conversation_id" | "message_id">;
}

export interface ConversationDetail {
  id: number;
  title: string;
  language: string;
  messages: ConversationMessage[];
}

export interface Transcript {
  text: string;
  language: string;
  confidence: number;
  needs_confirmation: boolean;
}
