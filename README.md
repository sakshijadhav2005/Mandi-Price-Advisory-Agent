# Mandi Price & Advisory Agent

A multilingual (English, Hindi, Marathi) agent that helps small farmers decide whether to **sell now or hold** their vegetables (28 of them: onion, tomato, potato, brinjal, okra, cauliflower, cabbage, chillies, gourds, beans, peas, leafy greens, garlic, ginger and more) in any of India's 789 districts. Nashik and Pune (Maharashtra) are the pilot, with hand-checked markets. It answers with a recommendation, a confidence level, the reasoning, and the sources it used, and it says "not enough data" when prices are stale. See [docs/plan.md](docs/plan.md) for the full plan.

> **Status: code for all five plan phases is in place, running on synthetic prices.** Real Agmarknet / data.gov.in ingestion is implemented but not yet connected (it needs an API key and confirmation that the pilot mandis publish daily). The assistant advises only on mandi prices and sell/hold; storage, scheme and other questions get a pointer to the local agriculture office or KVK. Every synthetic price is tagged as such in the API and UI.

## What's here

| Path | What it does |
|---|---|
| `backend/app/agent/decision.py` | Deterministic sell / hold / insufficient-data engine: net price after transport and fees, a damped 14-day trend plus last year's change over the same weeks (when a year of history exists), storage cost, storage weight loss, volatility-based confidence, and a staleness rule (> 3 days). Uses only the farmer's district markets, or the markets within 60 km of their location. Includes the plan's baselines. |
| `backend/app/agent/tools.py` | The 5 agent tools (`check_data_freshness`, `get_mandi_prices`, `search_advisories`, `estimate_transport_cost`, `compute_recommendation`), with strict JSON schemas and source tracking. |
| `backend/app/agent/llm_agent.py` | Claude tool-use loop (`claude-opus-5-5`, low effort, server-side refusal fallback enabled) with the fixed 6-call tool budget. |
| `backend/app/agent/guardrails.py` | Rejects LLM answers in the wrong language, or with any figure that can't be traced to a tool result. A rejected answer is replaced by the template writer. |
| `backend/app/agent/fallback.py` | Template answer writer in all 3 languages. Used when no LLM is configured, so the app and evaluation run offline. |
| `backend/app/ingestion/` | data.gov.in API adapter, Agmarknet CSV importer, synthetic generator. |
| `backend/app/api/` | FastAPI: `/auth/otp/*`, `/auth/google`, `/chat`, `/ws/chat`, `/prices`, `/conversations`, `/feedback`, `/voice/*`, `/meta`. OpenAPI docs at `/docs`. |
| `backend/app/voice/` | Whisper speech-to-text, Sarvam AI, Google Cloud and Azure text-to-speech (with an answer cache), and WER/CER metrics. |
| `backend/app/alerts.py`, `api/alerts.py` | Price alerts: thresholds checked after each daily ingestion, Expo push to phones, in-app inbox for the web. |
| `backend/app/api/admin.py` | Pilot monitoring: `/admin/stats` (answers, helpful rate, voice share, latency per language) and `/admin/export.csv`. Enabled by `ADMIN_TOKEN` (send it as `X-Admin-Token`). |
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
| Answers | The template writer (default). It gives the same decision, numbers and sources as any LLM, answers government-scheme questions from the scheme entries, storage questions from reviewed documents, everyday crop questions from Kisan Call Centre answers, pesticide waiting-period questions from the reviewed CIB&RC list, and weather and spraying questions from the district's IMD bulletin (forecast in the farmer's language; crop advice text in English with a link). Other questions get a short pointer to the agriculture office or KVK. |
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

Weekly district farm advice: `python manage.py fetch-agromet` downloads the IMD agromet advisory bulletin (Gramin Krishi Mausam Sewa) for each district in `AGROMET_DISTRICTS` (default `pune`). It runs as part of `daily`, and `manage.py schedule` also runs it at 14:00 and 20:00 because bulletins come out twice a week at no fixed hour. A download is stored only if it is a real PDF with readable text and an issue date, and not the bulletin already stored; the district's previous bulletin is then marked superseded. Answers use a bulletin only until the last day of its forecast, and bulletins and their PDFs (`backend/data/agromet/`) are deleted after `AGROMET_RETENTION_DAYS` (30). When no valid bulletin is left, the assistant says so and `OPS_ALERT_WEBHOOK_URL` gets an alert. Plan for the other advisory features: [docs/rag-plan.md](docs/rag-plan.md).

Safe spraying (waiting period before harvest): the official CIB&RC "Major uses of pesticides" lists (PPQS) go in `backend/data/rag-sources/3-pesticides/`. `pip install -e ".[pesticides]"`, then `python manage.py import-pesticides` reads them, keeps the rows for the app's crops as **pending** and writes `backend/data/pesticides/review.csv` (original cells included; doubtful rows flagged). An agronomist marks rows `yes`/`no` (and may correct values), then `python manage.py approve-pesticides review.csv --reviewer "Name"` makes the approved rows usable. Answers use only approved rows, never mix one product's name with another's waiting period, give the longest waiting period when the product is unclear, and count the days left when the farmer says when they sprayed. `daily` checks the PPQS page on the 1st of each month and sends an ops alert when a newer list is published (`python manage.py check-pesticide-list` runs it by hand).

Government schemes: one structured entry per scheme in `backend/data/schemes/<id>.json` (benefit, who can get it, who cannot, documents, how to apply, official link, helpline, `info_as_of`, `review_status`) in English, Hindi and Marathi, with yes/no eligibility rules whose questions live in `_facts.json`. Shipped: PM-KISAN, Namo Shetkari (Maharashtra), PMFBY crop insurance, Kisan Credit Card, drip/sprinkler subsidy, Soil Health Card, Magel Tyala solar pump (Maharashtra) and e-NAM, all as **draft** (written from official sources on 2026-11-21, not yet checked by an officer). A reviewer corrects an entry if needed and sets `"review_status": "reviewed"` and `"reviewed_by"`. Farmers only get central schemes and their own state's; "am I eligible?" is answered by the rules (eligible / not eligible with the reason / the questions that decide it), never guessed; every answer gives the official link and helpline, and says so when an entry is unreviewed or older than six months. `python manage.py check-schemes` validates the files and lists entries that need attention; `daily` alerts ops monthly about outdated ones.

Storage and post-harvest advice: add official documents (ICAR-DOGR, CPRI, KVK, agricultural universities) with `python manage.py add-document FILE --title "..." --crop onion --language mr --publisher "ICAR-DOGR" [--url https://...]` (PDF, Markdown or text; split into passages at headings). A document starts as **pending** and is used only after `python manage.py approve-document ID --reviewer "Name"` (`reject-document`, `list-documents`). Storage questions are answered from the best matching passage of an approved document for that crop, in the farmer's language, naming the document. No documents ship with the app.

Scanned PDFs, or Marathi PDFs in old fonts that extract as garbage (MPKV's Krishidarshani), go through OCR first: install Tesseract (`winget install UB-Mannheim.TesseractOCR`), put `mar.traineddata` / `hin.traineddata` from tessdata_best in `backend/data/tessdata/`, then `python tools/ocr_pdf.py book.pdf out_dir FIRST LAST` (needs `pip install pymupdf`). Check the OCR text against the PDF before approving the document.

Kisan Call Centre answers: everyday crop questions (varieties, nutrients, water, crop care) are answered from similar questions that KCC experts answered for farmers in the same district (`KCC_DISTRICTS`, default `pune`, last `KCC_YEARS` = 3 years). Load them with `python manage.py import-kcc kcc.csv` (the CSV export of "Kisan Call Centre (KCC) - Transcripts of farmers queries & answers" from data.gov.in) or, with `KCC_RESOURCE_ID` set, `python manage.py fetch-kcc` (also monthly in `daily`). Weather, scheme and market rows are skipped, number-encoded Devanagari in old rows is decoded, duplicates are dropped, and **any answer that names a pesticide or a dose is not stored**: doses come only from the reviewed CIB&RC list. Search is a small built-in BM25 with Marathi/Hindi stemming and glossary-based cross-language expansion; a crop name alone never counts as a match.

Admin page (`/admin` on the web and **Admin** at the bottom of Settings in the mobile app; needs `ADMIN_TOKEN`; uploads are on the web page): what the advisory features still need (pesticide rows to review, approved documents, KCC answers, the current IMD bulletin, scheme entries needing attention), and upload / approve / reject storage documents with the reviewer's name recorded.

Official scheme pages: `python manage.py watch-sources` (every Monday in `daily`) fingerprints each scheme's official page (ignoring scripts, tags and numbers) and sends an ops alert naming the entries to re-check when a page's text changes. The first check only records the pages.

Single-district deployment: `LOCKED_DISTRICT=pune` makes every answer, price list and alert use Pune, and `/meta` lists only Pune, so the web and mobile apps hide their district picker. Empty (default) serves all districts.

Login protection: failed password logins are limited per account (`AUTH_MAX_FAILURES`, 5) and per IP address (`AUTH_IP_MAX_ATTEMPTS`, 30), OTP codes per phone number (`OTP_MAX_REQUESTS`, 5) and signups per IP (`SIGNUP_MAX_PER_IP`, 10), each within `AUTH_WINDOW_MINUTES` (15); over the limit the API answers 429 with Retry-After. Counters are per server process by default; `RATE_LIMIT_BACKEND=database` shares them through the database across every worker and server.

Advisory evaluation: `python evaluation/scripts/run_advisory_eval.py` asks the labelled questions in `evaluation/test_sets/advisory_questions.jsonl` (English, Hindi, Marathi) against sample content for every feature and reports routing and content accuracy per language and feature (`evaluation/reports/advisory_results.md`); the test suite runs it too, so a routing regression fails the build.

Sarvam AI (one `SARVAM_API_KEY`): `TTS_PROVIDER=sarvam` for spoken answers, `STT_PROVIDER=sarvam` for voice questions (model `SARVAM_STT_MODEL`, default `saaras:v4`; phone m4a and browser webm audio), and machine translation of each new IMD bulletin's crop advice into Marathi and Hindi, made once when it is downloaded (`python manage.py translate-agromet` adds it to bulletins stored earlier). Translated advice is marked as a machine translation; without a key, the template answer writer gives the forecast in the farmer's language and links the English bulletin.

Answer writer naming: answers come from an AI model (`mode: "llm"`) or, when none is configured or an AI answer fails a guardrail, from the **template answer writer** (`mode: "template"`; answers saved before this rename say `"offline"`, which means the same). Both need the server; "template" does not mean without internet.

Real prices: set `DATA_GOV_IN_API_KEY` (free, from your data.gov.in account) and run `python manage.py daily` once a day. On Windows, `.\deploy\install-daily-task.ps1` (in PowerShell) registers a Task Scheduler job for 18:30 that runs `deploy\daily.ps1` and catches up when the PC was off (log in `backend/daily.log`; run it at once with `Start-ScheduledTask -TaskName MandiDaily`); on Linux use cron, or leave `manage.py schedule` running. Each API call is retried three times with a 20 s pause, because data.gov.in is often slow. It fetches prices, checks price alerts, and posts to `OPS_ALERT_WEBHOOK_URL` (Slack, Discord or Teams) when ingestion fails or returns nothing. Or import Agmarknet CSV exports with `python manage.py import-csv file.csv`.

How the feed is mapped onto the pilot markets:
- `DATA_GOV_IN_RESOURCE_ID` picks the dataset; the default is "Variety-wise Daily Market Prices". The fetch filters by state and commodity only, because Agmarknet has spelt districts both "Nasik" and "Nashik".
- Markets are matched **exactly** against the `agmarknet_names` listed per market in `backend/data/reference.json` (Agmarknet lists Pune(Moshi), Pune(Pimpri) and others separately, so substring matching is not safe). Rows for markets that are not listed are logged with their published names, so you can add a spelling after the first run.
- Agmarknet publishes one row per variety. The `agmarknet_varieties` list per crop picks the main variety (for onion "Red" first); if none of the listed varieties is present, the varieties are averaged, weighted by arrivals when known.
- The feed only has the current day. Backfill history from an Agmarknet CSV export with `import-csv` so the 14-day trend and the seasonal signal have something to work with.
- When real rows arrive, they take priority over synthetic rows for the same market and day. Run `python manage.py purge-synthetic` to drop the demo prices altogether.

## Tests

```bash
cd backend && python -m pytest          # decision engine, guardrails, Claude/Gemini/Groq/Ollama loops (fake servers), API, voice, alerts, admin, districts, ops alerts
node node_modules/vitest/vitest.mjs run  # in packages/shared and apps/web
```

On Windows, `npm run build`, `npm run typecheck` and `npm test` fail while the project folder name contains `&` (cmd.exe splits the path at it). Rename the folder, or call the tools through node from the package folder, for example in `apps/web`: `node ../../node_modules/typescript/bin/tsc --noEmit -p .` and `node ../../node_modules/vite/bin/vite.js build`.

End-to-end (web app + real backend with synthetic prices, at 360 px phone width, in your installed Chrome):

```bash
cd apps/web
node ../../node_modules/@playwright/test/cli.js test   # or: npx playwright test
```

Mobile UI flows (Maestro, on an emulator or phone with the app installed and the backend running): `maestro test apps/mobile/.maestro`.

Optional backend extras: `pip install -e ".[s3]"` and `S3_BUCKET=...` to keep consented voice recordings in S3-compatible storage. Recordings are kept only when `STORE_VOICE_RECORDINGS=true` **and** the farmer turns on "keep my voice recordings" in Settings; otherwise they are deleted right after transcription.

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
- Per-language checks of the template-writer pipeline (crop understanding, answer language, number grounding, citation validity) are 100% in English, Hindi and Marathi.

These numbers only show the pipeline works. They say nothing about real-market performance until the test set is rebuilt from Agmarknet history.

Voice: `python evaluation/scripts/voice_eval.py evaluation/test_sets/voice_manifest.csv` reports WER, CER and intent accuracy per language. The included `voice_manifest.example.csv` has 6 typed examples to show the format; the plan's 30–50 recorded samples per language still need to be collected.

Pilot: import prices farmers actually received with `python manage.py import-csv sales.csv --source pilot_ground_truth`, and watch `/admin/stats` during the pilot.

## Login

Login and signup are one step: the first successful login creates the account, and the server then issues its own JWT (HS256, `JWT_SECRET`).

- **Mobile number + OTP.** In dev mode (`OTP_DEV_MODE=true`) the code is shown on screen instead of being sent by SMS.
- **Sign in with Google** (OAuth 2.0 / OpenID Connect). Create an OAuth client ID of type "Web application" in Google Cloud Console, add your web origin (for example `http://localhost:5173`) under "Authorised JavaScript origins", and set `GOOGLE_CLIENT_ID`. The button then appears on the login page. The server checks the Google ID token's signature against Google's keys, plus its audience, issuer, expiry and verified email. A Google account and a phone account are separate accounts.

## Adding a crop, market or language

- All of India: `backend/data/india_districts.json` lists every district with its state and centre, built by `python tools/build_india_districts.py INDIA_DISTRICTS.geojson` from the MIT-licensed boundaries in [datta07/INDIAN-SHAPEFILES](https://github.com/datta07/INDIAN-SHAPEFILES) (the script fixes the file's broken characters and adds old names such as Aurangabad and Bangalore as aliases). Each district starts with one main market at its centre; the daily `fetch-data-gov` run registers every other market Agmarknet reports in a known district (table `agmarknet_markets`). Until a district has real prices, it gets two years of demo prices the first time someone opens it, labelled as demo data; set `DEMO_PRICES=false` to turn that off, and real prices replace a district's demo prices automatically.
- District, market or crop: add it to `backend/data/reference.json` (names, aliases, coordinates, storage cost, loss rate). A crop's `agmarknet_commodity` must be the exact Agmarknet commodity name (for example `Bhindi(Ladies Finger)`); list other published spellings in `agmarknet_commodity_aliases`. When a question names two crops' aliases, the longest one wins, so "shimla mirch" is capsicum, not chilli. Give it a demo price profile in `backend/app/ingestion/synthetic.py` and run `python manage.py seed-synthetic`. Each district lists its markets. Farmers pick a district in Settings, or the server uses the markets within `nearby_radius_km` of their location.
- Language: add `backend/data/languages/<code>.json` (copy `en.json`, translate every template) and `packages/i18n/src/locales/<code>.json`, then list it in `packages/i18n/src/index.ts`. Tests fail if any key is missing.

## What still needs people, accounts or devices

These can't be done in code:

- **Real data:** a `DATA_GOV_IN_API_KEY` (or Agmarknet CSV history), then rebuild the test set and rerun the evaluation.
- **API keys:** `ANTHROPIC_API_KEY` for Claude answers (then run `run_eval.py --llm`); a Sarvam AI key (best for Marathi), or a Google or Azure key, for server text-to-speech.
- **Native-speaker review** of `backend/data/languages/{hi,mr}.json` and `packages/i18n/src/locales/{hi,mr}.json`.
- **Devices:** test the Expo and Capacitor apps on a real low-end Android phone (microphone, speech, push); create an EAS project and a Play Store internal testing track.
- **Pilot:** 3–5 farmers or traders and recorded voice samples per language, then a narrated demo with real prices and the resume bullet with measured numbers.

Already done: a 48-second screen walkthrough on synthetic data, [docs/demo/mandi-advisor-demo.mp4](docs/demo/mandi-advisor-demo.mp4), with phone-width screenshots in [docs/screenshots](docs/screenshots). Re-record with `UI_CHECK_WEB=http://localhost:5173 python evaluation/scripts/ui_check.py --video`, then `ffmpeg -i docs/demo/mandi-advisor-demo.webm -c:v libx264 -pix_fmt yuv420p -an docs/demo/mandi-advisor-demo.mp4`. Hindi and Marathi review sheets for a native speaker are in [docs/review](docs/review) (`python tools/translation_review.py apply mr docs/review/translations_mr.csv` applies the corrections).
