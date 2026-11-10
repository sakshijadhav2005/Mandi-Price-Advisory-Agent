# Mandi Price & Advisory Agent — Project Plan

## 1. Project Summary

A multilingual, voice-and-chat agentic RAG system that helps small farmers decide whether to **sell now or hold** their produce. Farmers can ask questions by typing or speaking in their own language, and receive a spoken or written answer with reasoning, a confidence level, and sources.

The agent:

1. Understands the farmer's query in any supported language (text or voice).
2. Retrieves recent mandi (wholesale market) prices for the crop from nearby markets.
3. Retrieves relevant crop-advisory bulletins (storage, quality, weather notes).
4. Calls tools to compare prices, estimate storage and transport cost, and check data freshness.
5. Produces a sell/hold recommendation with reasoning, confidence, and sources, in the farmer's language.

It must state uncertainty clearly and flag stale or missing data rather than give false precision.

## 2. Goals and Non-Goals

**Goals**
- Give a clear sell/hold recommendation with visible reasoning and cited sources.
- Support multiple Indian languages in both text and voice, starting with 3 languages.
- Support voice input (speech-to-text) and voice output (text-to-speech), with chat as a fallback.
- Say "insufficient data" when prices are stale or missing.
- Evaluate recommendations against realized prices from past windows.
- Ship the same product as a website and as Android/iOS mobile apps from one shared frontend codebase.

**Non-goals**
- Guaranteeing profit or replacing a trader's judgment.
- Trading futures or contracts.
- Covering all crops or all states in v1.
- Offline-first operation in v1 (listed as a later phase).

## 3. Scope for v1

- **Crops:** 2 crops (e.g., onion and tomato).
- **Geography:** One district plus its 3–5 nearest mandis.
- **Languages:** 3 languages for v1 (e.g., English, Hindi, Marathi), chosen based on the pilot region. Architecture must allow adding more without code changes.
- **Interfaces:** Chat (text) and voice (speech-to-text and text-to-speech), both available on web and mobile.
- **Platforms:** Website, Android app, iOS app.
- **Users:** Simulated farmer queries first; a pilot with 3–5 real farmers or traders.

## 4. Full Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend (web) | React + Vite + TypeScript | Website UI |
| Frontend (mobile) | React Native (Expo) | Native mobile screens |
| Mobile/web wrapper | Capacitor | Packaging the React web app as Android/iOS shells, native plugins (microphone, storage, notifications) |
| Shared code | Monorepo with shared TypeScript package | API client, types, translations, and business logic reused by web and mobile |
| Styling | Tailwind CSS (web) / React Native styles (mobile) | Consistent design tokens across platforms |
| Internationalization | i18next (web) and i18next with react-i18next for RN | Translation strings, language switching, RTL readiness |
| Backend API | Python with FastAPI | REST and WebSocket endpoints |
| Agent framework | LangGraph or a custom tool-use loop | Agent orchestration |
| LLM | Hosted multilingual LLM (provider chosen by budget) | Reasoning and generation in multiple languages |
| Speech-to-text | Whisper (self-hosted) or a cloud STT API | Converting farmer voice input to text |
| Text-to-speech | Cloud TTS (e.g., Google or Azure Indic voices) or open-source Indic TTS | Spoken answers in the farmer's language |
| Translation | LLM-based with glossary; optional dedicated MT model | Keeping agricultural terms consistent |
| Vector search | FAISS or Qdrant | Embedding-based advisory retrieval |
| Keyword search | BM25 (rank_bm25 or Elasticsearch-lite) | Hybrid retrieval with embeddings |
| Relational database | PostgreSQL (SQLite for local dev) | Prices, users, conversations, evaluation logs |
| Background jobs | Celery or APScheduler | Daily price ingestion and bulletin indexing |
| Auth | Phone-number OTP or JWT | Farmer login using a mobile number |
| Hosting | Docker; backend on a small cloud VM or container service | Deployment |
| Storage | S3-compatible object storage | Voice recordings (optional, with consent) and bulletin PDFs |
| Testing | pytest (backend), Vitest and Playwright (web), Jest and Detox or Maestro (mobile) | Automated tests |
| Monitoring | Sentry for errors; structured logs | Production visibility |

## 5. Architecture

```
                 ┌──────────────────────────────────────────┐
                 │        Shared TypeScript package         │
                 │  API client · types · i18n strings · UI   │
                 │  logic · voice-state hooks                │
                 └───────────────┬──────────────────────────┘
                                 │
        ┌────────────────────────┼─────────────────────────┐
        ▼                        ▼                         ▼
 React web app          React Native app          Capacitor wrapper
 (Vite + Tailwind)      (Expo, Android/iOS)       (packages web app as
                                                    Android/iOS shells,
                                                    native mic/audio)
        │                        │                         │
        └────────────┬───────────┴─────────────────────────┘
                     │  HTTPS / WebSocket (text + audio)
                     ▼
        ┌──────────────────────────────────────────┐
        │           Python backend (FastAPI)        │
        │                                           │
        │  Voice gateway                            │
        │   ├── STT (audio → text, language detect) │
        │   └── TTS (text → audio, target language) │
        │                                           │
        │  Agent service (LangGraph / tool loop)    │
        │   ├── get_mandi_prices()                  │
        │   ├── search_advisories()                 │
        │   ├── estimate_transport_cost()           │
        │   ├── check_data_freshness()              │
        │   └── decision: sell / hold / insufficient│
        │                                           │
        │  Translation layer (query and answer)     │
        │  Auth · session · conversation history    │
        └──────────┬───────────────────┬────────────┘
                   ▼                   ▼
         PostgreSQL              Vector + BM25 index
     (prices, users,            (advisory bulletins,
      conversations, evals)      chunked with metadata)
                   ▲
                   │
        Ingestion jobs (daily price pull, bulletin indexing)
```

**Language flow**
1. Farmer speaks or types in their language (e.g., Marathi).
2. STT converts speech to text and detects language (for typed input, the language is set in the app).
3. The agent works internally on the normalized query; the retrieval layer also searches bulletins in their original language where available.
4. The answer is generated in the farmer's language, with an English-language audit log kept for evaluation.
5. TTS produces audio if voice output is selected.

**Voice flow**
- Mobile and web capture audio through the browser or Capacitor microphone plugin.
- Audio is sent to the backend, transcribed, passed to the agent, and the answer returns as text plus optional audio.
- A "speak again" and a "show text" option are always available, because voice recognition will fail on noisy field conditions.

## 6. Components in Detail

**Frontend (React web)**
- Pages: login (phone OTP), home (ask a question), conversation view, price dashboard, settings (language choice), history.
- Chat input with a large microphone button, since many users will be on low-end phones.
- Language selector on first launch; the choice persists.
- Responsive layout tested at 360px width.

**Mobile (React Native with Expo)**
- Same screens and shared logic as the web app, using React Native components.
- Native microphone and audio playback.
- Push notifications for daily price alerts (optional in v1).

**Capacitor**
- Used to wrap the React web build as the Android and iOS app shell where a web-first approach is faster, and to access native features (microphone permissions, file storage, device language detection).
- Decision point (Week 1): choose whether the mobile app uses React Native or Capacitor as the primary native path. The plan assumes both are kept with a shared codebase so either can be the release path. See Section 13.

**Backend (Python / FastAPI)**
- `/auth` — phone OTP login, token refresh.
- `/chat` — text query, returns answer, sources, confidence, language.
- `/voice/transcribe` — audio in, text and detected language out.
- `/voice/speak` — text in, audio out.
- `/prices` — current and historical prices by crop and market.
- `/conversations` — history per user.
- `/feedback` — farmer marks an answer as helpful or not (used in evaluation).
- WebSocket `/ws/chat` — optional streaming of agent steps and partial answers.

**Agent**
- Fixed tool budget (e.g., 6 calls per query).
- Staleness rule: prices older than 3 days produce "insufficient data."
- Every recommendation includes confidence, sources, and a plain-language reason.
- Output is always in the user's selected language, with a standard disclaimer translated.

**Data pipelines**
- Daily job pulls mandi prices and stores them with timestamp, market, crop, min/modal/max.
- Weekly job indexes new advisory bulletins (PDF text extraction, chunking, language tagging, embedding).
- Failed ingestion raises an alert and updates the freshness status.

## 7. Multilingual Design

- **Translation strategy:** UI strings in i18n files (JSON per language). Agent answers generated directly in the target language, with a glossary of agricultural terms (e.g., onion variety names, mandi terms) to keep translations consistent.
- **Evaluation in each language:** Test set includes queries in every supported language; accuracy is reported per language.
- **Bulletins:** Store original language and tag it; retrieval can search the original and return an English or translated summary.
- **Numbers and currency:** Format rupees and quantities per locale.
- **Fonts and scripts:** Devanagari and other scripts must render on Android and iOS; test with low-end devices.
- **RTL readiness:** Not needed for initial languages, but the layout should not hard-code left alignment.

## 8. Voice Design

- **Input:** Tap-and-hold or tap-to-start microphone. Show a visible recording indicator and a cancel button.
- **Language detection:** Use STT's detected language; let the user override it in settings.
- **Noise and failure handling:** If transcription confidence is low, show the transcript and ask the user to confirm or retype.
- **Output:** Read answers aloud with a play button; keep the text visible alongside audio.
- **Low-bandwidth:** Compress audio (Opus) before upload; keep answers short enough to listen to in under 30 seconds.
- **Privacy:** Ask for consent before storing voice recordings. Default is to delete audio after transcription.

## 9. Data Plan

| Source | What | Access method | Risk |
|---|---|---|---|
| Government agri-marketing portals / open-data sites | Daily mandi prices | Download or API | Gaps, delays, format changes |
| State agriculture extension bulletins | Storage and quality advice | PDF / web | Outdated, mixed languages |
| Local trader or farmer interviews | Ground truth on real prices received | Manual collection | Small sample size |

**Action item (Week 1):** Confirm which portal publishes the target crop and market data, and whether it is updated daily.

## 10. Evaluation Plan

**Test set**
- 100–200 historical decision points: crop, market, date, prices known at that time.
- Each labeled with the outcome: the best nearby price 7 days later, net of storage and transport.
- Label as "sell" or "hold."
- Add 30–50 spoken query samples in each language for voice evaluation (word error rate and intent accuracy).

**Metrics**
- Recommendation accuracy (overall and per language).
- Insufficient-data rate (should be high when data is stale, not guessed).
- Citation accuracy: does each claim trace to a retrieved source?
- Speech recognition word error rate per language.
- Answer quality per language, rated by native-speaking reviewers.
- Cost per query and latency (text and voice separately).
- Calibration: when the agent says "high confidence," how often is it right?

**Baselines**
- Always-sell and always-hold.
- Rule: sell if today's price is above the 7-day average.

## 11. Two-Week Build Plan (MVP)

Two weeks is tight for this full scope. The plan below delivers the core agent and the web app in two weeks; voice, mobile, and extra languages follow in later phases (Section 12).

**Week 1: Data, backend, and baseline**
- Day 1–2: Identify and download price data for 2 crops and 3–5 markets; set up monorepo and FastAPI skeleton.
- Day 3: Load prices into PostgreSQL (SQLite locally); write freshness checks.
- Day 4: Build the labeled historical test set; implement baseline rules and measure them.
- Day 5: Index advisory bulletins (chunk, embed, BM25); build hybrid retrieval.

**Week 2: Agent, web app, and evaluation**
- Day 6–7: Implement the agent with tool calls, decision step, and guardrails.
- Day 8: Add the `/chat` endpoint and the React web app with text chat and language selector (English + one other language).
- Day 9: Run full evaluation against baselines; record failure cases.
- Day 10: Add voice input and output for the web app using a cloud STT/TTS API.
- Day 11–12: Polish UI, test at 360px width, test translations with a native speaker.
- Day 13–14: Record a 2-minute demo, write the README and results, and write the resume bullet with measured numbers.

## 12. Phased Roadmap

**Phase 1 (Weeks 1–2): MVP**
- Web app, text chat, 2 languages, 2 crops, 1 district.
- Baselines and evaluation.

**Phase 2 (Weeks 3–5): Voice and third language**
- Voice input and output on web.
- Add third language and evaluate per-language quality.
- Speech evaluation (word error rate).

**Phase 3 (Weeks 6–8): Mobile apps**
- React Native (Expo) app sharing business logic and API client with web.
- Capacitor build for Android as a comparison or fallback path.
- Native microphone and audio testing on real devices.
- Play Store internal testing track.

**Phase 4 (Weeks 9–10): Pilot**
- Deploy backend and web app.
- Pilot with 3–5 real farmers or traders; collect feedback.
- Fix top issues from pilot.

**Phase 5 (later): Expansion**
- More crops, districts, and languages.
- Offline mode with cached prices.
- Push notifications for price alerts.

## 13. Decision: React Native vs. Capacitor for Mobile

Both are listed because they serve different needs, but one should be the primary mobile path to avoid double maintenance.

| Option | Strengths | Weaknesses |
|---|---|---|
| React Native (Expo) | True native UI, better performance on low-end Android, strong native module ecosystem | Separate UI components from web; more code to keep in sync |
| Capacitor (wrap React web app) | Maximum code reuse with the web app; faster to ship | Relies on web rendering; audio and mic behavior depends on native plugins |

**Recommendation:** Use React Native (Expo) as the primary mobile path, because it gives better performance on low-end phones, which matters for this audience. Share the API client, types, i18n strings, and business logic through the monorepo. Use Capacitor only if a web-first release is needed sooner or if the React web app is already mature and screens can be reused directly. Make this final decision at the end of Phase 2.

## 14. Repository Structure

```
mandi-agent/
├── apps/
│   ├── web/                 # React + Vite web app
│   ├── mobile/              # React Native (Expo) app
│   └── capacitor/           # Capacitor config (optional)
├── packages/
│   ├── shared/              # API client, types, business logic, hooks
│   └── i18n/                # Translation JSON files per language
├── backend/
│   ├── app/
│   │   ├── api/             # FastAPI routers
│   │   ├── agent/           # Agent graph, tools, guardrails
│   │   ├── voice/           # STT and TTS adapters
│   │   ├── retrieval/       # Vector + BM25 search
│   │   ├── ingestion/       # Price and bulletin pipelines
│   │   ├── translation/     # Glossary and translation helpers
│   │   └── db/              # Models and migrations
│   ├── tests/
│   └── pyproject.toml
├── evaluation/
│   ├── test_sets/           # Labeled decision points, voice samples
│   ├── scripts/             # Evaluation and baseline runners
│   └── reports/
├── docs/
│   ├── plan.md
│   └── README.md
└── docker-compose.yml
```

## 15. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Price data missing or delayed | Freshness check; answer "insufficient data" instead of guessing |
| Small labeled dataset | Multiple markets and time windows; report confidence intervals |
| Agent over-confident | Calibration metric; force a confidence level in output |
| Poor speech recognition in noisy fields or regional accents | Show transcript for confirmation; allow retyping; measure WER per language |
| Translation errors in agricultural terms | Glossary; native-speaker review; per-language evaluation |
| Scope creep (3 languages, 2 platforms, voice) | Phased roadmap; lock v1 to web text chat first |
| Cost of LLM and STT/TTS APIs | Budget per query; cache repeated price answers; choose self-hosted Whisper if volume grows |
| Low-end Android performance | Test on a real low-end device; keep UI lightweight |
| Two mobile paths causing double work | Single primary path decided in Section 13; shared logic package |
| Farmer relies on output for large decisions | Clear disclaimer in every language; decision support, not advice |
| Privacy of voice and phone data | Consent for recordings; delete audio by default; encrypt at rest |

## 16. Deliverables

- [ ] Working web app with text and voice chat in 3 languages
- [ ] React Native (Expo) mobile app for Android and iOS
- [ ] Capacitor build (if chosen as fallback)
- [ ] FastAPI backend with documented API (OpenAPI)
- [ ] Labeled evaluation set (text and voice) and evaluation scripts
- [ ] Results table: agent vs. baselines, per language
- [ ] Failure analysis section
- [ ] README with setup instructions for backend, web, and mobile
- [ ] 2-minute demo video
- [ ] Resume bullet with measured results

## 17. Open Questions

- Which portal provides reliable daily prices for the target crop and market?
- Which three languages will the pilot region need first?
- Which LLM provider and STT/TTS provider fit the budget, and do they support the chosen Indic languages well?
- Is there a local farmer or trader willing to give feedback on the pilot?
- Will the mobile app be distributed through Play Store only at first, or also through iOS TestFlight?
- What is the monthly infrastructure budget for hosting, APIs, and storage?
