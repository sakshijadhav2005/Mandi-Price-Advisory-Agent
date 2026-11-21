# Mandi Price & Advisory Agent

A multilingual (English, Hindi, Marathi) agent that helps small farmers decide whether to **sell now or hold** their vegetables (28 of them: onion, tomato, potato, brinjal, okra, cauliflower, cabbage, chillies, gourds, beans, peas, leafy greens, garlic, ginger and more) in any of India's 789 districts. Nashik and Pune (Maharashtra) are the pilot, with hand-checked markets. It answers with a recommendation, a confidence level, the reasoning, and the sources it used, and it says "not enough data" when prices are stale. See [docs/plan.md](docs/plan.md) for the full plan.

> **Status: code for all five plan phases is in place, running on synthetic prices.** Real Agmarknet / data.gov.in ingestion is implemented but not yet connected (it needs an API key and confirmation that the pilot mandis publish daily). The app ships with no advisory documents: add official ones (crop bulletins, government schemes) as described under "Advisory documents and government schemes" below. Every synthetic price is tagged as such in the API and UI.

## What's here

| Path | What it does |
|---|---|
| `backend/app/agent/decision.py` | Deterministic sell / hold / insufficient-data engine: net price after transport and fees, a damped 14-day trend plus last year's change over the same weeks (when a year of history exists), storage cost, storage weight loss, volatility-based confidence, and a staleness rule (> 3 days). Uses only the farmer's district markets, or the markets within 60 km of their location. Includes the plan's baselines. |
| `backend/app/agent/tools.py` | The 5 agent tools (`check_data_freshness`, `get_mandi_prices`, `search_advisories`, `estimate_transport_cost`, `compute_recommendation`), with strict JSON schemas and source tracking. |
| `backend/app/agent/llm_agent.py` | Claude tool-use loop (`claude-opus-5-5`, low effort, server-side refusal fallback enabled) with the fixed 6-call tool budget. |
| `backend/app/agent/guardrails.py` | Rejects LLM answers in the wrong language, or with any figure that can't be traced to a tool result. A rejected answer is replaced by the template writer. |
| `backend/app/agent/fallback.py` | Template answer writer in all 3 languages. Used when no LLM is configured, so the app and evaluation run offline. |
| `backend/app/retrieval/index.py` | Hybrid retrieval: BM25 + character n-gram vectors, fused with RRF, with glossary-based cross-language query expansion. |
| `backend/app/ingestion/` | data.gov.in API adapter, Agmarknet CSV importer, synthetic generator. |
| `backend/app/api/` | FastAPI: `/auth/otp/*`, `/auth/google`, `/chat`, `/ws/chat`, `/prices`, `/conversations`, `/feedback`, `/voice/*`, `/meta`. OpenAPI docs at `/docs`. |
| `backend/app/voice/` | Whisper speech-to-text, Sarvam AI, Google Cloud and Azure text-to-speech (with an answer cache), and WER/CER metrics. |
| `backend/app/alerts.py`, `api/alerts.py` | Price alerts: thresholds checked after each daily ingestion, Expo push to phones, in-app inbox for the web. |
| `backend/app/api/admin.py` | Pilot monitoring: `/admin/stats` (answers, helpful rate, voice share, latency per language) and `/admin/export.csv`. Document management: `/admin/documents` (list, upload PDF/Markdown/text, delete uploads); an upload is indexed at once and the agent answers from it on the next question. Enabled by `ADMIN_TOKEN`; the web app's **Admin** page (link at the bottom of Settings, or `/admin`) uses it. |
| `backend/app/db/retention.py` | Deletes chat questions and answers (and their feedback) older than `HISTORY_RETENTION_DAYS` (30) at startup and every hour; `python manage.py purge-history` runs it by hand. |
| `backend/data/languages/*.json` | Language packs: answer templates, glossary, speech locale, script. Adding a language needs no code change. |
| `packages/shared` | TypeScript API client, types, formatting helpers and the voice state machine, shared by web and mobile. |
| `packages/i18n` | UI strings per language (i18next JSON). |
| `apps/web` | React + Vite + Tailwind web app: first-launch language picker, chat with mic button, price dashboard with alerts, history, settings, OTP login. Installable PWA that shows the last prices offline. |
| `apps/mobile` | React Native (Expo SDK 52) app, the primary mobile path: same screens, server speech-to-text from on-device recording, the server's voice when one is configured (else on-device text-to-speech), push price alerts, offline price cache. |
| `apps/capacitor` | Fallback mobile path: the web build wrapped as Android and iOS apps (`android/` and `ios/` projects generated, microphone, speech and location permissions added). |
| `deploy/`, `docker-compose.yml`, `.github/workflows/ci.yml` | Web container (nginx), full stack with Postgres and the daily ingestion and alert job, CI for tests and builds. |
| `evaluation/` | Test-set builder, evaluation runner and results report. |

## Run it

Backend (Python 3.11+):

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env              # optional
python manage.py seed-synthetic   # 2 years of synthetic prices ending today
uvicorn app.main:app --reload --port 8000
python manage.py ask "मी कांदा आता विकू की थांबू?" --lang mr   # quick CLI check
```

### Free setup (no paid API keys)

Everything runs without paying for anything:

| Part | Free option |
|---|---|
| Answers | The template writer (default). It gives the same decision, numbers and sources as any LLM, and answers storage and handling questions from the bulletin passages in the farmer's language. |
| Prices | A free data.gov.in API key (sign up on data.gov.in) for `fetch-data-gov`, or Agmarknet CSV downloads for `import-csv`. |
| Voice input | The browser's speech recognition on the web; `pip install faster-whisper` and `STT_PROVIDER=whisper` for the mobile app. |
| Spoken answers | The browser's or phone's speech engine (`TTS_PROVIDER=none`). For clear Marathi and Hindi, set `TTS_PROVIDER=sarvam` and `SARVAM_API_KEY` (Sarvam AI Bulbul voices); the web and mobile apps then play the server's voice. |
| Push alerts | Expo's push service, with a free Expo account. |

**Optional free hosted LLM (Gemini, Groq or OpenRouter).** For natural answers in all three languages without paying, get a free key and put it in `backend/.env`:
- Gemini (recommended, good Hindi and Marathi): `GEMINI_API_KEY=...` from https://aistudio.google.com/apikey
- Groq: `GROQ_API_KEY=...` from https://console.groq.com/keys
- OpenRouter: `OPENROUTER_API_KEY=...` from https://openrouter.ai/keys (uses a `:free` model)

With `LLM_PROVIDER=auto` the first key set is used (Gemini, then Groq, then OpenRouter). Change the model with `GEMINI_MODEL`, `GROQ_MODEL` or `OPENROUTER_MODEL`. The same guardrails apply, and if the free quota runs out (HTTP 429) the template answer is used instead. Free tiers may use your prompts to improve their models; the prompts contain the farmer's question and the price data, not phone numbers.

**Optional free local LLM (Ollama).** For more natural English answers, run `ollama pull qwen2.5:3b` and `ollama serve`, then set `LLM_PROVIDER=ollama`. It's opt-in because of what testing on this project showed with the 3B model:
- English answers were often good. The guardrails rejected the ones that invented a number, recommended the wrong decision ("Hold your onions" for a sell result), or answered in the wrong language, and the template answer was used instead.
- Some accepted answers still explained the reasoning badly; for example, one called the price after holding a "holding cost". The guardrails can't catch that.
- Hindi and Marathi were not good enough, so by default the local model answers only in English (`OLLAMA_LANGUAGES=en`). With 16 GB of RAM, try `OLLAMA_MODEL=qwen2.5:7b` and `OLLAMA_LANGUAGES=en,hi,mr`, then check the answers yourself.

`GET /meta` shows which writer is active (`answer_writer`).

Claude (paid) is optional: set `ANTHROPIC_API_KEY` and `auto` switches to it (it takes priority over the free keys).

Web app (Node 20+), from the repo root:

```bash
npm install
npm run dev        # http://localhost:5173
```

> **Windows note:** npm scripts fail when the folder path contains `&` (as in `Mandi Price & Advisory Agent`), because npm runs them through `cmd.exe`. Either rename the folder (e.g. `mandi-agent`) or call the tools directly: `node node_modules/vite/bin/vite.js apps/web`, `node node_modules/vitest/vitest.mjs run`, `node node_modules/typescript/bin/tsc --noEmit -p apps/web`.

Mobile (Expo): `cd apps/mobile && npx expo start`, then open in Expo Go or an Android emulator. The default server address is `http://10.0.2.2:8000` (the emulator's view of your PC); change it in Settings for a real phone. Push notifications need an EAS project id in `app.json`. Voice input on mobile needs `STT_PROVIDER=whisper` on the backend.

Capacitor fallback: `npm run build -w apps/web`, then in `apps/capacitor`: `npx cap sync android && npx cap open android` (needs Android Studio). iOS, on a Mac with Xcode and CocoaPods: `npx cap sync ios && npx cap open ios`.

Docker (Postgres + API + web + daily ingestion and alert job): `docker compose up --build`, then `docker compose exec api python manage.py seed-synthetic`.

Real prices: set `DATA_GOV_IN_API_KEY` (free, from your data.gov.in account) and run `python manage.py daily` once a day. On Windows, `.\deploy\install-daily-task.ps1` registers a Task Scheduler job for 18:30 (log in `backend/daily.log`); on Linux use cron, or leave `manage.py schedule` running. Each API call is retried three times with a 20 s pause, because data.gov.in is often slow. It fetches prices, checks price alerts, and posts to `OPS_ALERT_WEBHOOK_URL` (Slack, Discord or Teams) when ingestion fails or returns nothing. Or import Agmarknet CSV exports with `python manage.py import-csv file.csv`.

How the feed is mapped onto the pilot markets:
- `DATA_GOV_IN_RESOURCE_ID` picks the dataset; the default is "Variety-wise Daily Market Prices". The fetch filters by state and commodity only, because Agmarknet has spelt districts both "Nasik" and "Nashik".
- Markets are matched **exactly** against the `agmarknet_names` listed per market in `backend/data/reference.json` (Agmarknet lists Pune(Moshi), Pune(Pimpri) and others separately, so substring matching is not safe). Rows for markets that are not listed are logged with their published names, so you can add a spelling after the first run.
- Agmarknet publishes one row per variety. The `agmarknet_varieties` list per crop picks the main variety (for onion "Red" first); if none of the listed varieties is present, the varieties are averaged, weighted by arrivals when known.
- The feed only has the current day. Backfill history from an Agmarknet CSV export with `import-csv` so the 14-day trend and the seasonal signal have something to work with.
- When real rows arrive, they take priority over synthetic rows for the same market and day. Run `python manage.py purge-synthetic` to drop the demo prices altogether.

## Tests

```bash
cd backend && python -m pytest          # decision engine, guardrails, retrieval, Claude/Gemini/Groq/Ollama loops (fake servers), API, voice, alerts, admin, districts, ops alerts
node node_modules/vitest/vitest.mjs run  # in packages/shared and apps/web
```

On Windows, `npm run build`, `npm run typecheck` and `npm test` fail while the project folder name contains `&` (cmd.exe splits the path at it). Rename the folder, or call the tools through node from the package folder, for example in `apps/web`: `node ../../node_modules/typescript/bin/tsc --noEmit -p .` and `node ../../node_modules/vite/bin/vite.js build`.

End-to-end (web app + real backend with synthetic prices, at 360 px phone width, in your installed Chrome):

```bash
cd apps/web
node ../../node_modules/@playwright/test/cli.js test   # or: npx playwright test
```

Mobile UI flows (Maestro, on an emulator or phone with the app installed and the backend running): `maestro test apps/mobile/.maestro`.

Optional backend extras: `pip install -e ".[semantic]"` and `RETRIEVAL_EMBEDDER=sentence-transformers` for multilingual sentence embeddings (a Marathi question then matches English bulletins without the glossary); `pip install -e ".[s3]"` and `S3_BUCKET=...` to keep consented voice recordings in S3-compatible storage. Recordings are kept only when `STORE_VOICE_RECORDINGS=true` **and** the farmer turns on "keep my voice recordings" in Settings; otherwise they are deleted right after transcription.

## Evaluation

```bash
cd backend
python ../evaluation/scripts/build_test_set.py          # 200 decision points + 40 simulated feed outages
python ../evaluation/scripts/run_eval.py --pipeline 5   # add --llm to evaluate Claude answers (costs money)
```

Latest results on synthetic data (2 districts × 3 crops: 600 decision points plus 120 outages) are in [evaluation/reports/results.md](evaluation/reports/results.md). In summary:

- The engine scores **75.2%** (95% CI 71.5–78.5%) against 71.8% for always-sell, 43.2% for the 7-day-average rule and 28.2% for always-hold. Before the seasonal signal was added it scored 72.7%; the gain came mostly from potato. The intervals overlap with always-sell, and the synthetic generator has seasonality built in, so only real Agmarknet history can show whether this holds up.
- Its biggest misses are still potato in July–October 2025, the first year of data, when there is no year-before history for the seasonal signal.
- On simulated feed outages it says "insufficient data" **100%** of the time. All baselines guess.
- Its confidence levels are meaningful: high-confidence calls are right 93% of the time, medium 71%, low 48%.
- Per-language checks of the offline pipeline (crop understanding, answer language, number grounding, citation validity) are 100% in English, Hindi and Marathi.

These numbers only show the pipeline works. They say nothing about real-market performance until the test set is rebuilt from Agmarknet history.

Voice: `python evaluation/scripts/voice_eval.py evaluation/test_sets/voice_manifest.csv` reports WER, CER and intent accuracy per language. The included `voice_manifest.example.csv` has 6 typed examples to show the format; the plan's 30–50 recorded samples per language still need to be collected.

Pilot: import prices farmers actually received with `python manage.py import-csv sales.csv --source pilot_ground_truth`, and watch `/admin/stats` during the pilot.

## Login

Login and signup are one step: the first successful login creates the account, and the server then issues its own JWT (HS256, `JWT_SECRET`).

- **Mobile number + OTP.** In dev mode (`OTP_DEV_MODE=true`) the code is shown on screen instead of being sent by SMS.
- **Sign in with Google** (OAuth 2.0 / OpenID Connect). Create an OAuth client ID of type "Web application" in Google Cloud Console, add your web origin (for example `http://localhost:5173`) under "Authorised JavaScript origins", and set `GOOGLE_CLIENT_ID`. The button then appears on the login page. The server checks the Google ID token's signature against Google's keys, plus its audience, issuer, expiry and verified email. A Google account and a phone account are separate accounts.

## Adding a crop, market or language

- All of India: `backend/data/india_districts.json` lists every district with its state and centre, built by `python tools/build_india_districts.py INDIA_DISTRICTS.geojson` from the MIT-licensed boundaries in [datta07/INDIAN-SHAPEFILES](https://github.com/datta07/INDIAN-SHAPEFILES) (the script fixes the file's broken characters and adds old names such as Aurangabad and Bangalore as aliases). Each district starts with one main market at its centre; the daily `fetch-data-gov` run registers every other market Agmarknet reports in a known district (table `agmarknet_markets`). Until a district has real prices, it gets two years of demo prices the first time someone opens it, labelled as demo data; set `DEMO_PRICES=false` to turn that off, and real prices replace a district's demo prices automatically.
- **Advisory documents and government schemes:** the agent answers storage, handling and scheme questions only from documents you add; it ships with none. Upload PDF, Markdown or text files on the admin page (`/admin`, needs `ADMIN_TOKEN`), or put them in `backend/data/bulletins/` and restart. For each document set the language, the crop (or "all"), **which state it applies to** ("all" for central schemes; a state-only document is never used for farmers elsewhere), and for schemes the **official link and helpline**, which the answer then gives the farmer. A Markdown file sets these in a header:

  ```
  ---
  id: pm-kisan-mr
  title: पीएम-किसान योजना
  crop: all
  language: mr
  state: all
  source: Ministry of Agriculture, PM-KISAN operational guidelines
  published: 2025-04-01
  url: https://pmkisan.gov.in
  helpline: 155261
  ---
  ```

  A PDF takes the same lines in a `.meta` file next to it (`pm-kisan.pdf` + `pm-kisan.meta`). Scanned PDFs need OCR first. Upload the Marathi and Hindi versions where they exist: retrieval prefers the farmer's language, and the offline answer writer only answers a Marathi or Hindi farmer from a document in that language.
- District, market or crop: add it to `backend/data/reference.json` (names, aliases, coordinates, storage cost, loss rate). A crop's `agmarknet_commodity` must be the exact Agmarknet commodity name (for example `Bhindi(Ladies Finger)`); list other published spellings in `agmarknet_commodity_aliases`. When a question names two crops' aliases, the longest one wins, so "shimla mirch" is capsicum, not chilli. Give it a demo price profile in `backend/app/ingestion/synthetic.py` and run `python manage.py seed-synthetic`. Each district lists its markets. Farmers pick a district in Settings, or the server uses the markets within `nearby_radius_km` of their location. Then add advisory documents for any new crop (see below).
- Language: add `backend/data/languages/<code>.json` (copy `en.json`, translate every template) and `packages/i18n/src/locales/<code>.json`, then list it in `packages/i18n/src/index.ts`. Tests fail if any key is missing.

## What still needs people, accounts or devices

These can't be done in code:

- **Real data:** a `DATA_GOV_IN_API_KEY` (or Agmarknet CSV history), then rebuild the test set and rerun the evaluation. Add official extension bulletins and scheme documents.
- **API keys:** `ANTHROPIC_API_KEY` for Claude answers (then run `run_eval.py --llm`); a Sarvam AI key (best for Marathi), or a Google or Azure key, for server text-to-speech.
- **Native-speaker review** of `backend/data/languages/{hi,mr}.json` and `packages/i18n/src/locales/{hi,mr}.json`.
- **Devices:** test the Expo and Capacitor apps on a real low-end Android phone (microphone, speech, push); create an EAS project and a Play Store internal testing track.
- **Pilot:** 3–5 farmers or traders and recorded voice samples per language, then a narrated demo with real prices and the resume bullet with measured numbers.

Already done: a 48-second screen walkthrough on synthetic data, [docs/demo/mandi-advisor-demo.mp4](docs/demo/mandi-advisor-demo.mp4), with phone-width screenshots in [docs/screenshots](docs/screenshots). Re-record with `UI_CHECK_WEB=http://localhost:5173 python evaluation/scripts/ui_check.py --video`, then `ffmpeg -i docs/demo/mandi-advisor-demo.webm -c:v libx264 -pix_fmt yuv420p -an docs/demo/mandi-advisor-demo.mp4`. Hindi and Marathi review sheets for a native speaker are in [docs/review](docs/review) (`python tools/translation_review.py apply mr docs/review/translations_mr.csv` applies the corrections).
