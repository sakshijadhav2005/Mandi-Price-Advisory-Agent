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

/** This week's IMD agromet advisory for the farmer's district. */
export interface AgrometSource {
  id: string;
  kind: "agromet";
  title: string;
  district: string;
  issued_on: string;
  valid_until: string;
  url: string;
  origin: string;
}

/** The reviewed CIB&RC "major uses of pesticides" list (dose, waiting period before harvest). */
export interface PesticideSource {
  id: string;
  kind: "pesticide";
  title: string;
  list_date: string;
  url: string;
  origin: string;
}

/** A government scheme entry (official link and helpline; "draft" until an officer reviews it). */
export interface SchemeSource {
  id: string;
  kind: "scheme";
  title: string;
  info_as_of: string;
  review_status: "draft" | "reviewed";
  url: string;
  helpline: string;
  origin: string;
}

/** A reviewed official storage / post-harvest document. */
export interface DocumentSource {
  id: string;
  kind: "document";
  title: string;
  publisher: string;
  url: string | null;
  published: string | null;
  origin: string;
}

/** A Kisan Call Centre answer to a similar farmer question in the district. */
export interface KccSource {
  id: string;
  kind: "kcc";
  title: string;
  asked_on: string;
  question: string;
  origin: string;
}

export type Source = PriceSource | AgrometSource | PesticideSource | SchemeSource | DocumentSource | KccSource;

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
  /** Every state and union territory that has districts, sorted. */
  states?: string[];
  language_packs?: LanguagePackInfo[];
  district: { name: string; state: string };
  languages: Record<string, string>;
  crops: Named[];
  markets: (Named & { lat: number; lon: number; district?: string })[];
  voice: { server_stt: boolean; server_tts: boolean; stores_recordings?: boolean };
  auth_required: boolean;
  /** OAuth 2.0 client ID; set when the server offers "Sign in with Google". */
  google_client_id?: string | null;
  /** Set when the server serves one district only (LOCKED_DISTRICT); the apps then hide the district picker. */
  locked_district?: string | null;
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

/** A storage / post-harvest document on the admin page. */
export interface AdminDocument {
  id: number;
  title: string;
  crop: string;
  language: string;
  publisher: string;
  url: string | null;
  published: string | null;
  file_name: string;
  status: "pending" | "approved" | "rejected";
  reviewed_by: string | null;
  passages: number;
  created_at: string | null;
}

export interface DocumentUpload {
  file: Blob;
  filename: string;
  title: string;
  crop: string;
  language: string;
  publisher: string;
  url?: string;
  published?: string;
}

/** Review work left and content available to the advisory features (GET /admin/content). */
export interface AdminContent {
  pesticide_rows: Record<string, number>;
  documents: Record<string, number>;
  kcc_answers: number;
  schemes: { total: number; needs_attention: string[] };
  agromet: { district: string; issued_on: string; valid_until: string }[];
}

