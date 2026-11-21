# Advisory knowledge (RAG) plan: Pune district

Status, 2026-11-21: **feature 1 (this week's farm advice) is built** (`backend/app/advisory/agromet.py`,
`manage.py fetch-agromet`, tool `get_district_advisory`, tests in `backend/tests/test_agromet.py`).
**Feature 3 (safe spraying) is built** (`backend/app/advisory/pesticides.py`, `manage.py import-pesticides` / `approve-pesticides` / `check-pesticide-list`, tool `lookup_pesticide`, tests in `backend/tests/test_pesticides.py`); it answers only once a reviewer has approved rows. **Feature 5 (government schemes) is built** (`backend/app/advisory/schemes.py`, entries in `backend/data/schemes/`, tools `list_schemes` / `get_scheme` / `check_scheme_eligibility`, `manage.py check-schemes`, tests in `backend/tests/test_schemes.py`); entries are drafts until reviewed. **Features 2 and 4 are built** (`backend/app/advisory/kcc.py`, `documents.py`, shared search in `search.py`; commands `import-kcc` / `fetch-kcc` and `add-document` / `approve-document`; tools `search_farmer_questions` and `search_storage_advice`; tests in `backend/tests/test_knowledge.py`) but have **no content yet**: KCC rows need the data.gov.in CSV or `KCC_RESOURCE_ID` (the API was timing out and the dataset page refuses automated access on 2026-11-22), and storage documents need to be obtained from ICAR-DOGR / CPRI / KVK (their sites refused connections). Other questions are pointed to the agriculture office or KVK.

## 1. Goal and scope

Extend the advisor beyond prices, for **Pune district only**, with five kinds of
knowledge. Each one is used only where it is the right tool:

| # | Feature | Example question | Approach |
|---|---|---|---|
| 1 | This week's farm advice | "पाऊस येणार आहे का, टोमॅटो काढू का?" | Retrieval over the current IMD district bulletin, hard expiry |
| 2 | Everyday crop questions | "कांद्याची पाने पिवळी पडतात, काय करू?" | Hybrid search over Kisan Call Centre answers |
| 3 | Safe spraying | "फवारणीनंतर किती दिवसांनी टोमॅटो विकू शकतो?" | Structured lookup (not text search) over CIB&RC tables |
| 4 | Storage and post-harvest | "रब्बी कांदा किती दिवस साठवू शकतो?" | Retrieval over reviewed extension documents |
| 5 | Government schemes | "पीक विमा कसा काढायचा?" | Structured scheme entries + eligibility rules; retrieval only for long guidelines |

Out of scope: prices (already a database and decision engine), pest diagnosis from
photos, loans and legal questions.

Principles:

- **Numbers never come from free text.** Prices come from the decision engine; doses and
  waiting periods from the structured pesticide table; scheme amounts from reviewed entries.
- **Hard filters, not preferences.** District = Pune, document still valid, document
  reviewed. A chunk that fails any filter is never retrieved.
- **No relevant passage, no answer.** Below a relevance threshold the assistant says it
  does not know and points to KVK Narayangaon / KVK Baramati or the taluka agriculture office.
- **Every answer cites its source and date**, with the official link.

## 2. Source documents

Downloaded on 2026-11-21 into `backend/data/rag-sources/` (PDFs are git-ignored; the list
with URLs and SHA-256 fingerprints is in `backend/data/rag-sources/manifest.json`).

| Feature | Document | Publisher | Status |
|---|---|---|---|
| 1 | Pune agromet advisory, dated 20.11.2026 (English, 6 pages, readable text) | IMD Gramin Krishi Mausam Sewa, AMFU Pune, College of Agriculture Pune | Downloaded |
| 1 | Same bulletin in Marathi | IMD | **Pending**: the regional-language link is built by JavaScript on the IMD site |
| 2 | Kisan Call Centre questions and answers, Pune district | data.gov.in (resource "Kisan Call Centre (KCC) - Transcripts of farmers queries & answers") / ICAR KCC-CHAKSHU | **Pending**: data.gov.in API timing out on 2026-11-21 |
| 3 | Major uses of pesticides: insecticides, fungicides, herbicides, bio-insecticides, bio-fungicides, as on 30.09.2026 | CIB&RC, PPQS, Ministry of Agriculture | Downloaded (5 PDFs) |
| 3 | List of pesticides banned / restricted in India | CIB&RC | **Pending**: to locate on ppqs.gov.in |
| 4 | Onion storage and post-harvest publications (English; Marathi newsletter *Kanda va Lasun Samachar*) | ICAR-DOGR, Rajgurunagar (Pune) | **Pending**: DOGR site did not resolve; ICAR KRISHI repository refused connections |
| 4 | Potato storage (CPRI), tomato handling (KVK Narayangaon) | ICAR-CPRI, KVK | **Pending**: to collect |
| 5 | PMFBY revamped operational guidelines (2020) | Ministry of Agriculture | Downloaded |
| 5 | PM-KISAN operational guidelines | Ministry of Agriculture | **Pending**: pmkisan.gov.in TLS error |
| 5 | Maharashtra agriculture GRs (Marathi) | gr.maharashtra.gov.in | To collect per scheme |

Licences: data.gov.in content is under the Government Open Data License (attribution
required). For university and ICAR PDFs, confirm reuse terms or get written permission
for the pilot (MPKV and DOGR are both in the district).

## 3. Architecture

```
            farmer question (mr / hi / en, text or voice)
                              │
                 ┌────────────▼────────────┐
                 │ understand: language,   │  existing: crop, district,
                 │ crop, quantity, intent  │  quantity detection
                 └────────────┬────────────┘
     ┌──────────┬─────────────┼──────────────┬──────────────┬─────────────┐
  decision   weekly advice  crop question  spraying       storage       scheme
  (existing)    (#1)          (#2)          (#3)           (#4)          (#5)
     │           │             │             │              │             │
 price engine  bulletin      KCC hybrid    pesticide      document     scheme entry
               for Pune,     search        table lookup   search       + eligibility
               still valid                                (reviewed)   rules
     └───────────┴──────┬──────┴─────────────┴──────────────┴─────────────┘
                        ▼
          answer writer (LLM, or templates offline)
                        ▼
   guardrails: language · numbers grounded · decision consistent ·
               claims supported by passages · no dose unless from table #3
                        ▼
               answer + sources + date + official link
```

The existing pieces stay as they are: the decision engine, tool budget and deadline,
the number/language/decision guardrails and the template fallback.

### Shared storage (new tables)

```
rag_documents   id, feature, district, language, title, publisher, source_url,
                issued_on, valid_until, status (active | superseded | expired | pending_review),
                sha256, file_path, fetched_at, reviewed_by, reviewed_at
rag_chunks      id, document_id, crop, section, text, embedding (nullable)
pesticide_uses  id, list_date, chemical, formulation, crop, pest,
                dose_ai_per_ha, dose_formulation_per_ha, dilution_l_per_ha,
                waiting_days, source_file, source_page, verified_by
```

A chunk is only searchable when its document is `active`, `valid_until >= today`
(or empty for documents without expiry) and `reviewed_by` is set (except feature #1,
which is published by IMD and used as is).

## 4. Feature plans

### 4.1 This week's farm advice (built)

- **Source:** IMD current district bulletin,
  `https://mausam.imd.gov.in/imd_latest/contents/agromet/agromet-data/district/current/english-pdf/Pune.pdf`.
  Issued twice a week (committee meeting dates, e.g. 20.11.2026); contains last week's
  weather, a 5-day forecast, the extended-range outlook and crop-wise advice.
- **Download:** `python manage.py fetch-agromet`, run at 14:00 and 20:00 by the existing
  scheduler (`manage.py schedule` / Windows task). Same retry and timeout handling as the
  price fetch.
- **Validate:** response must start with `%PDF-`, be under 10 MB, and have extractable text.
  Compare the SHA-256 with the last stored bulletin: unchanged means stop.
- **Parse:** issue date from "committee meeting dated DD.MM.YYYY"; forecast window from
  "Weather Forecast (DD.MM.YYYY to DD.MM.YYYY)". `valid_until` = end of the forecast
  window (normally issue date + 4 days). Split into sections: weather summary, extended
  range, general advisory, and one section per crop.
- **Store:** new row in `rag_documents`; the previous Pune bulletin becomes `superseded`.
  Keep the PDF under `backend/data/agromet/pune/<issue-date>.pdf`.
- **Use:** filter Pune + `active` + valid; pick the crop's section plus the weather summary.
  No vector search needed (one short document). The sell/hold answer adds one line when the
  forecast has rain or a heat alert in the next days.
- **Expire and delete:** excluded the moment `valid_until` passes or a newer bulletin
  arrives. The existing hourly cleanup deletes bulletins and PDFs older than
  `AGROMET_RETENTION_DAYS` (default 30).
- **Failure:** IMD down: keep using the last bulletin until it expires, then answer "no
  current district advisory; see the Meghdoot app or KVK". Ops alert (existing webhook)
  when Pune has no valid bulletin for 2 days.
- **Marathi:** answer in Marathi from the English bulletin; switch to the Marathi bulletin
  once its link is known.

### 4.2 Everyday crop questions (Kisan Call Centre) (built; needs data)

- **Source:** data.gov.in KCC transcripts API, filtered to state Maharashtra, district Pune,
  and the app's crops. Same API key as prices.
- **Download:** monthly `manage.py fetch-kcc`; incremental by month.
- **Clean:** keep the last 3 years; drop answers naming a banned or restricted pesticide
  (list from CIB&RC); drop empty or one-word answers; merge near-duplicate questions.
- **Search:** this is the one real search problem (thousands of short Q&A pairs, mixed
  English / transliterated Marathi): BM25 + multilingual embeddings, fused, then a
  relevance threshold.
- **Rule:** never pass on a chemical dose from a KCC answer; if the answer names a
  chemical, take dose and waiting period from feature #3 or leave them out.
- **Delete:** rows older than 3 years removed monthly.
- **Unknown until the API responds:** how many Pune rows exist and how good they are. Check
  this before building.

### 4.3 Safe spraying and waiting period before harvest (built; needs a reviewer)

- **Source:** the five CIB&RC "major uses" PDFs as on 30.09.2026 (downloaded).
- **Convert:** text extraction works but table rows span several lines, so use a table
  extractor (e.g. pdfplumber) and then **have a person verify** every row for the app's
  crops (onion, tomato, potato, and the other supported vegetables). Only verified rows
  are used.
- **Use:** structured lookup by crop + pest or chemical. Answers quote dose and waiting
  period exactly, with the list date. Main question: "can I harvest and sell N days after
  spraying X?"
- **Update:** quarterly check of the PPQS page for a newer list date. A new version is
  imported as `pending_review` and replaces the old one only after approval. The old
  version is kept 1 year for audit.
- **Safety:** no dose for a crop/chemical pair that is not in the list; mention protective
  equipment and following the label.

### 4.4 Storage and post-harvest (built; needs documents)

- **Sources:** ICAR-DOGR onion storage material (English, Marathi newsletter), CPRI potato
  storage, KVK Narayangaon tomato handling. Collected by hand; no feed.
- **Ingest:** admin upload (PDF/Markdown), split by heading, tagged crop and language.
  OCR for scanned PDFs, with a check of extracted text quality.
- **Review:** each document needs `reviewed_by`; review date shown on the admin page;
  flagged when older than 2 years.
- **Use:** hybrid search, crop filter, relevance threshold. Supports the hold decision
  ("storage loss per week", "curing before storage").

### 4.5 Government schemes (built; entries are drafts until reviewed)

- **Structured entries** (one per scheme, en/hi/mr): who is eligible, benefit, documents,
  how to apply, official link, helpline, information-as-of date, review status.
  Start with PM-KISAN, PMFBY, KCC, Soil Health Card, PM-KUSUM, micro-irrigation,
  Namo Shetkari, Magel Tyala Saur Krushi Pump.
- **Eligibility rules** as yes/no checks (land in own name, income tax payer, government
  employee, ...); the assistant asks only the questions that decide the answer.
- **Retrieval** only over long official guidelines (e.g. PMFBY operational guidelines) for
  questions the entry does not cover.
- **Change watch:** weekly check of gr.maharashtra.gov.in (Agriculture department) for new
  GRs; new GRs are **flagged for review**, never published automatically.
- **Expiry:** entry flagged when its information-as-of date is older than 6 months.

## 5. Evaluation

Run on every change; block a release when faithfulness or grounding drops.

| Layer | Metric | Test set |
|---|---|---|
| Intent routing | accuracy per language | ~300 real Pune farmer questions, labelled |
| Retrieval | recall@5, MRR, correct "no answer" rate | question → correct chunk pairs, mr/hi/en |
| Answers | faithfulness to passages, numbers grounded, citation valid, language | same questions, automatic checks |
| Weekly advice | never uses an expired or non-Pune bulletin | fake IMD server tests |
| Spraying | every dose/waiting period matches a verified table row | table-driven tests |
| Human review | Marathi naturalness, usefulness, safety | agronomist + native speaker, 50 answers a month |

## 6. Build order

| Step | Work | Depends on |
|---|---|---|
| 1 | Weekly advice (4.1): fetch, parse, expire, delete, answer, tests | nothing (source available) |
| 2 | Spraying table (4.3): extract, verify rows for app crops, lookup tool | a reviewer for the rows |
| 3 | Storage documents (4.4): collect DOGR/CPRI/KVK material, review, search | DOGR site reachable or documents by email |
| 4 | Schemes (4.5): structured entries, eligibility rules, GR watch | reviewer for entries |
| 5 | KCC questions (4.2): fetch, clean, hybrid search | data.gov.in API responding |

## 7. Open decisions

1. Lock the app to Pune district (hide the district picker, Pune markets only)?
2. Who reviews pesticide rows and scheme entries (agronomist, KVK contact)?
3. Ask MPKV / DOGR for permission and for Marathi originals of their material?
4. Which AI model writes answers in production (affects Marathi quality and cost)?
