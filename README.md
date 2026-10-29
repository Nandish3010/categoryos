# CategoryOS

An agentic category manager that cuts category-team workload: it decides whether to bet ₹X on a new vendor (which SKUs, at what terms), then keeps the category running, and proves every number it states.

Built for the Meta Global AI Developer Hackathon (indie track), Oct 26 - Nov 4, 2026.

> **Status.** The four vendor runs the public site replays were **recorded live on 2026-10-27** against the Meta models (Muse Spark, Muse Image, SAM 3.1). `make dev` and the tests still run in **mock** mode (the real pipeline against hand-written model fixtures). The eval numbers below are deterministic verifier results on synthetic data, not model results. All vendors, SKUs, prices and documents are synthetic.

## What it does

**Onboard** a new vendor: **screen** (documents, claims, prompt-injection check) → **decide** (a verdict per SKU from rules over market data, with live margin and MOQ levers) → **negotiate** (gap table against the application, a deal evaluator for conditional offers, a live-call copilot) → **catalog** (listing copy, packshots, compliance flags) → **launch** (marketing, joint business plan, PO). Bring your own vendor at `/try` with a SKU sheet.

**Run** the existing category (`/run`): a weekly **MIS** review of vendor performance, a **PO tracker** that reads vendor replies and drafts the chaser, **price requests** (a vendor wants an 8-12% rise: the agent reads the email, Python decides each SKU, a person approves) **catalog fixes** (a queue of listing errors with a fix per row), a **promotions and event planner** (which SKUs to put on a sale, at what depth, with what stock and vendor funding) and a **competitor price monitor** (undercuts, blips, vendor parity breaches).

**The playbook** (`config/policy.yaml`, edited at `/rules`) holds every rule a category manager would tune: margins, thresholds, compliance documents, negotiation requirements, approval tiers, the SKU taxonomy. Nothing is hardcoded to pets; beauty and electronics playbooks ship in `config/examples/`.

**The verifier**: every number an agent states cites a source cell and is re-checked by Python; a wrong reading is sent back for correction, and a claim that never gets right is removed before it reaches the page.

## Quickstart

```bash
make setup   # uv sync + npm ci
make demo    # backend (replay mode) on :8001 and frontend on :3000
```

Then open http://localhost:3000/vendors/V001.

`make demo` plays back recorded runs of the full pipeline with their original pacing: no API keys, no database, no network. Approve, override, reject and re-plan all work on your session. `make dev` runs the same app in **mock** mode (the pipeline actually executes against canned model fixtures, with a local SQLite database). Neither needs keys. Prerequisites: [uv](https://docs.astral.sh/uv/), Node 20+.

## Meta models used

| Model | What it does here | Where | Without it |
|---|---|---|---|
| `muse-spark-1.3` | Reasoning, extraction, tool calling and narrative for every agent | `backend/app/llm.py` (`call`, `run_tools`), used by `agents/decide.py:run`, `agents/screen.py:run`, `agents/negotiate.py:run`, `agents/catalog.py:run`, `agents/launch.py:run`, `agents/pricereq.py:analyse`, `agents/dealflow.py:extract`, `copilot.py:_extract`, `ops/review.py:generate`, `ops/chaser.py:read_replies`, `ops/promotions/agent.py:generate` (reads funding replies, writes the event brief and funding emails), `ops/pricewatch/agent.py:generate` (daily summary, vendor parity messages), `ops/inventory_health/agent.py:generate` (weekly summary, action notes, vendor messages) | No agent output; only the deterministic metrics remain |
| `muse-spark-1.3` (vision) | Reads vendor scans (certificates, labels, price lists) with bounding boxes | `backend/app/docs.py:_read_page` | Declared document status is used |
| `muse-spark-1.3-contributor` | Cheaper development model; used by `make contract`. Not wired into a pipeline stage | `backend/app/config.py` (`Settings.model_text_dev`) | Dev loops use the main model |
| Muse Spark Open via Baseten (`meta-models/muse-spark-open-1026`) | SKU classification of messy vendor sheets, compared with the rules classifier | `backend/app/agents/catalog.py:classify` | Falls back to the deterministic taxonomy |
| `sam-3.1` | Packshot cutouts; finds a label's nutrition and claims panel so it can be cropped and read again | `backend/app/media.py` (`segment`, `segment_region`), used by `agents/catalog.py:_images`, `docs.py:_find_panel` | Original packshot with a label; label fields are read from their own boxes. Masks are arithmetic-coded and decoded with Meta's `meta-sam-parser` (pinned `==0.1.0`, a regular dependency), so real cutouts and panel regions work; the mask raster covers the box only and is placed at the box corner. The SAM License applies to that dependency. If decoding fails the box token is used |
| `muse-image-1.0` | Packshots, lifestyle and campaign images | `backend/app/media.py:generate_image`, used by `agents/catalog.py:_image`, `agents/launch.py:_campaign_image` | Labelled placeholder images |
| `muse-voice-transcribe-1.0` | Transcribes the vendor call (push-to-talk) | `backend/app/media.py:transcribe`, used by `copilot.py:transcribe`, `agents/negotiate.py:_asr` | The stored transcript fixture, with a banner |

Model names come from `backend/app/config.py`; every call goes through one gateway that switches mock / replay / live and enforces the spend cap.

## Feature details

CategoryOS takes a vendor from application to a launch-ready order in four phases, shown as eight stages in the UI.

| Phase | UI stages |
|---|---|
| Screen | 1 Intake |
| Decide | 2 Research, 3 Shortlist, 4 Negotiate |
| Execute | 5 Catalog |
| Launch | 6 Marketing, 7 JBP, 8 PO (shown as one "Launch packet" screen) |

These features carry the product:

- **Live what-if lever.** Drag target margin and MOQ and the shortlist re-scores instantly, showing capital at risk, days of cover and GMV. The numbers come from deterministic Python over the data, not from a model.
- **The verifier.** Every number the agents state cites a source cell (file, key, column). Each claim is re-checked against that cell. When the agent read a number wrong, it is told what the source says and tries again (up to `verifier.max_self_corrections`, default 2); the UI shows "Caught → corrected" with the attempts. A claim that never gets right is removed before it reaches the page.
- **The impact meter.** The app records how long a person actually spends reviewing each stage (from "ready for review" to approve) and counts their edits, then compares that with the playbook's by-hand baselines (`impact`: research estimates, not measured, until you replace them with your own time diary). The vendor workspace has a per-vendor drawer; the vendors board has a team projection that shows the share of the team's week in scope of the shipped modules, the share saved, and every module as shipped or not yet built, labelled estimate or measured.
- **Promotions and event planner (Run).** For each sale in the playbook calendar (a festive sale, a payday sale) Python plans from ops sales, stock and open POs: baseline demand lifted by the event, an uplift curve per category, units pulled forward, sales taken from near-duplicate SKUs, the stock-out check (a depth that would run out before the event ends is capped, or a stock-up PO is suggested if the vendor's lead time allows), the margin after vendor funding and the funding ask. The model reads the vendors' funding replies (every share, target and banner is checked against the email and self-corrected), the deal evaluator values conditional offers by Monte Carlo (an unreachable target counts as 0 and is countered), and the model writes the brief and the funding emails from engine numbers only: a sentence with a number that does not verify is struck. A person approves; POs and mails are simulated. Open `/run/promotions`; tune it in the Playbook (`promotions`).
- **Competitor price monitor (Run).** Thirty days of daily price snapshots from three marketplaces. Python separates a sustained undercut from a one-day blip (never matched) and a slow trend, flags a vendor selling under our price elsewhere or under MAP, and recommends match / hold / ask the vendor for price protection / flag the breach, with the margin impact over the horizon. Every number is a claim the verifier recomputes; the model drafts the daily summary and the vendor messages. Open `/run/price-watch`; tune it in the Playbook (`price_watch`).
- **Inventory health review (Run).** Weekly, per vendor and SKU: days of cover against a target band, stock-out risk (forecast demand against on-hand stock and the open POs' promised dates, late POs assumed to land later), aged and dead stock, excess from a vendor's minimum order quantity, and one recommended action each: reorder (quantity rounded up to the MOQ, with lead time), expedite a late PO, pause an overbought PO, return to the vendor under open sell-or-return terms, or liquidate on a promo (never under a cost floor). Python decides every number; each is a claim the verifier recomputes, and the model only drafts the plain-English notes and vendor messages (a sentence with a number that fails is struck). Approving is simulated. Open `/run/inventory-health`; tune it in the Playbook (`inventory_health`); data from `make data-inventory-health`.
- **Price requests (Run).** An existing vendor emails "we are revising prices by 8-12% from 1st Dec" with a messy price list and maybe a sweetener. The agent reads it into lines with verbatim quotes (checked and self-corrected); Python works out each SKU's new margin, the retail price that defends the target, the gap to competitors, elasticity risk, the 90-day GMV and margin impact and whether an input index justifies the rise; the deal evaluator's probability engine values volume-linked sweeteners; each SKU gets accept / accept partly (counter %) / pass through to price / delay / delist, an approval tier from the playbook's matrix, and a reply draft that only states engine numbers. A person approves; sending is simulated. Open `/run/price-requests`; tune it in the Playbook (`price_requests`).

- **Deal evaluator for conditional offers.** A vendor says "15% base margin, plus 20% marketing support if you sell 2,000 units in 90 days". The agent reads the structure; Python simulates demand (ramped new listing, fixed-seed Monte Carlo), gives the probability of hitting the target, prices the offer risk-adjusted in margin points, and rejects the structure with concrete counters (a target we can reach, a guaranteed base) when the chance is poor. Every number is a claim the verifier recomputes, and every assumption lives in the playbook (`negotiation.forecast`, `negotiation.contingent`).

- **Document vision.** Vendor documents arrive as scans and photos. muse-spark-1.3 reads the licence certificates, label photos and price-list PDF with bounding boxes; SAM 3.1 segments a label's nutrition and claims panel and the crop is read a second time; the verifier binds every reading to the page pixels and to that second read (new claim origin `vision_extraction`, evidence `{doc, page, bbox, crop_sha256}`); cross-document checks compare certificate vs application, label vs SKU sheet vs listing copy, and price list vs sheet. Screen treats the scanned certificate as ground truth over the declared status. Which documents, fields, pairs and tolerances: the playbook `documents` section. The synthetic scans (all marked SAMPLE) come from `data/generate_docs.py` (`make data-docs`).

- **Live negotiation copilot.** In Negotiate, "Live call" transcribes the call as it happens (push-to-talk buttons for who is speaking), reads what the vendor commits to, updates the gap table row by row, prices any conditional offer the moment it is said ("Don't accept: <0.1% chance") and suggests the buyer's next line with the reason. "Simulate call" streams the recorded call through the same pipeline from fixtures, so a replay or mock deployment shows it at no cost; a microphone call needs live mode and the demo key and has a per-call spend budget (`CALL_BUDGET_USD`).

Negotiate is transcript-first: the vendor call is transcribed and the commitments are extracted into a gap table against the application. Voice is layered on top.

## Live contract smoke

`make contract` (spends a few cents; needs `MODEL_API_KEY` and `BASETEN_API_KEY`) makes one tiny real call per external contract
(chat, reasoning-token limit, structured output, tool calling, vision, SAM 3.1, muse-image, ASR, Baseten), through the app's own
gateway code, and saves the scrubbed raw responses to `backend/fixtures/contract/`. `backend/tests/test_contract_fixtures.py`
replays those through the parsers offline (the recorded SAM mask is decoded through `meta-sam-parser`). `make contract ONLY="chat sam"` runs a subset.

SAM 3.1 returns the mask raster for the matched box only (live-verified: a 760x1100 label with box 18,261..737,1006 gave a 746x720 mask), so the app pastes it at the box corner plus the token's `x`/`y`. Decoding uses Meta's official `meta-sam-parser` from PyPI, pinned to 0.1.0; the SAM License applies to that dependency.

## Measured eval

`make eval` runs three checks and writes `eval/results/*.json`: the **verifier** against planted errors (digit
transposition, decimal shift, kg vs g, Rs vs paise, wrong row, wrong column, rounding beyond tolerance, spelled-out
numbers) with matched correct controls; the **extraction agent** through two models, graded by the verifier and the
self-correction loop; and **prompt injection** variants hidden in vendor text. It defaults to mock (free): the verifier
and injection checks run real code on synthetic data; the model comparison is not shown until a live run exists (the mock results keep scripted stand-ins in eval/results, never model names). `--live` runs the models
(needs `MODEL_MODE=live`, keys, credits). The table below is injected by `scripts/measure.py` and always names its mode.

<!-- eval:start -->
**Mode: live.** Live run: models called through the gateway. Seed 42, run 2026-10-27.

**Verifier** (no model; synthetic sheet, planted errors, matched correct controls)

| Error class | Planted | Caught | Recall | Recall (error above tolerance) | False positives (of matched controls) | Precision |
|---|---|---|---|---|---|---|
| Digit transposition | 25 | 23 | 92% | 100% (23/23) | 0 of 25 | 100% |
| Decimal shift | 25 | 25 | 100% | 100% (25/25) | 0 of 25 | 100% |
| kg vs g (or L vs ml) | 25 | 25 | 100% | 100% (25/25) | 0 of 25 | 100% |
| Rs vs paise | 25 | 25 | 100% | 100% (25/25) | 0 of 25 | 100% |
| Wrong row | 25 | 25 | 100% | 100% (25/25) | 0 of 25 | 100% |
| Wrong column | 25 | 25 | 100% | 100% (25/25) | 0 of 25 | 100% |
| Rounding beyond tolerance | 25 | 25 | 100% | 100% (25/25) | 0 of 25 | 100% |
| Spelled-out number | 25 | 25 | 100% | 100% (25/25) | 0 of 25 | 100% |
| **All** | 200 | 198 | 99.0% | 100.0% | 0 of 200 | 100.0% |

Misses are errors smaller than the playbook tolerance (₹1 on money, 1 point on percentages), which the verifier accepts by design.

**Extraction agent** (160 tasks, mode: live)

| Model | First-pass accuracy | Caught by verifier | Corrected on retry | Self-correction rate | Final accuracy | Silent errors | Cost | Tokens | Latency / task |
|---|---|---|---|---|---|---|---|---|---|
| muse-spark-1.3 (model A) | 100.0% | 0 | 0 | n/a | 100.0% | 0 | $0.0383 | 4469 in / 7696 out | 195 ms (extract call 31.2 s) |
| Muse Spark Open via Baseten (model B) | 100.0% | 0 | 0 | n/a | 100.0% | 0 | not metered | 4666 in / 8913 out | 95 ms (extract call 15.2 s) |

_Live: models called through the gateway (one batched extraction call per model over a clean synthetic sheet, so ceiling effects are expected); cost from the ledger, latency = total wall-clock / tasks. A self-correction rate of n/a means the verifier caught nothing to correct, so the retry loop was not exercised. Muse Spark Open on Baseten: cost is not metered (price unknown), token counts shown. Model-detector false positives varied between 1 and 3 of 30 across reruns._

**Prompt injection** (30 variants hidden in vendor text, 30 look-alike benign texts)

| Detector | Injections caught | Benign texts wrongly flagged |
|---|---|---|
| Regex guard (playbook `screening.injection_patterns`) | 9/30 (30%) | 0/30 (0%) |
| Model | 30/30 (100%) | 3/30 |
| Regex + model | 30/30 (100%) | |
<!-- eval:end -->

## Architecture

```
Next.js (Vercel) --HTTP + SSE--> FastAPI (Modal) --> Meta Model API (OpenAI SDK, https://api.meta.ai/v1)
                                       |               muse-spark-1.3 / -contributor, sam-3.1, muse-image-1.0,
                                       |               muse-voice-transcribe-1.0
                                       +--> Baseten: meta-models/muse-spark-open-1026 (sheet classification)
                                       +--> deterministic metrics (pure Python over data/synthetic)
                                       +--> SQLite: vendors, runs, events, claims, approvals
```

The backend gateway (`app/llm.py`) switches between mock and live, tracks cost against a spend cap, and falls back to fixtures on failure. `app/metrics.py` computes per-SKU metrics; `app/verify.py` re-checks claims.

## Modes

| Mode | What it does | Keys needed | Cost |
|---|---|---|---|
| `mock` | Executes the pipeline against hand-written fixtures for every model call. Default for `make dev` and the tests. | None | Free |
| `replay` | Plays back recorded golden runs (`backend/fixtures/golden/runs/`) as ephemeral in-memory sessions with their original pacing (gaps capped at 1.5 s). Re-plan serves cached narratives for the presets 0, +2, +4 at the default MOQ; other lever values return `narrative_unavailable`. The lever/metrics endpoint stays live. Default for `make demo` and the mode the Modal deploy is configured for. A golden run that fails its checksum, schema or metrics-hash check is served from the mock fixtures and flagged `degraded` in `GET /api/mode`. | None | Free |
| `live` | Calls the Meta Model API and Baseten for the stages in `LIVE_STAGES`; keyed routes need `X-Demo-Key`. | `MODEL_API_KEY`, `BASETEN_API_KEY` | Metered, capped by `MAX_SPEND_USD` |

The committed golden runs are **live** recordings (`meta.source: "live"`; `GET /api/mode` reports it per vendor). `make record` re-records them from the mock pipeline instead (free, deterministic, `meta.source: "mock"`). To re-record live (costs credits, honours `MAX_SPEND_USD`):
`cd backend && MODEL_MODE=live RECORD=1 uv run python -m app.record --vendor V001`. A live recording also writes the per-call stage fixtures (`backend/fixtures/golden/<stage>/`) and the generated images (`backend/fixtures/assets/`, untracked by default, so downscale and force-add them).

## Configuration

Only needed for live mode. Copy `.env.example` to `.env`.

| Variable | Purpose |
|---|---|
| `MODEL_API_KEY` | Meta Model API key |
| `MODEL_API_BASE_URL` | Meta Model API base URL |
| `BASETEN_API_KEY` | Key for Muse Spark Open on Baseten |
| `DEMO_KEY` | Server-side key that unlocks live calls on a deployed backend |
| `MODEL_MODE` | `mock`, `live` or `replay` |
| `LIVE_STAGES` | Comma-separated stages that run live when mode is `live` |
| `MAX_SPEND_USD` | Hard cap on model spend; live calls are refused above it |
| `CALL_BUDGET_USD` | Most one live copilot call may spend on transcription and extraction (default 2.00) |

## Configure the playbook

Every rule a category manager would tune (margin targets per category, vendor-type and brand offsets, demand and overlap
thresholds, compliance documents and claim rules, negotiation requirements, catalog and launch rules, PO tax and lead
times, lever bounds, verifier tolerances, and the SKU taxonomy) lives in one file: `config/policy.yaml`. The backend reads
it everywhere, and the model prompts are rendered from it, so no rule exists only in English or only in Python.

* Edit it in the UI at `/rules` (Playbook), or by hand: UI edits go to `config/policy.local.yaml` (gitignored); the
  effective playbook is the defaults deep-merged with that file. "Reset" deletes the override (or one section or field).
* `GET /api/policy` returns the effective playbook, the defaults, which paths are overridden and a hash; `PUT /api/policy`
  takes a partial. A rule change changes the metrics hash, so stale approvals are refused. Replay mode is read-only.
* Document vision is playbook-driven too: `documents` lists which scanned documents are read, which fields, which pairs are cross-checked and how closely they must agree, and `catalog.label_panel_prompt` is the phrase SAM uses to find a label's panel.
* Nothing is pet-specific in code. `config/examples/beauty.yaml` and `config/examples/electronics.yaml` are complete
  alternative playbooks (taxonomy, margins, documents such as CDSCO or BIS, claim rules, attributes, GST) that prove the
  engine is vertical-agnostic. Copy one over `config/policy.local.yaml` to try it; the demo data stays pet.
* Market facts (units per SKU, price bands) stay in `data/synthetic/category_benchmarks.json`; ops settings (spend caps,
  rate limits, timeouts) stay in env.

## Rules written as prompts, roles and a change log

On the Playbook page, **Write a rule** turns a plain-English sentence ("raise the target margin on treats by 2 points") into a preview of changes to existing playbook settings. The playbook stays structured data: the model (Muse Spark, strict `json_schema`) only picks settings that already exist and a number, switch or choice for each; Python builds the override, dry-runs it through the playbook's own validation and shows before/after values and the stages that read them from the validated result. A sentence is never stored as a rule, and free text, lists and whole rows cannot be set this way. A value the playbook rejects, or a setting that does not exist, comes back as an error with cause and fix and writes nothing.

* **Roles** live in the playbook's `governance` section (`config/policy.yaml`): team members (synthetic Meera = head, Arjun = manager, Priya = analyst), what each role may change and numeric limits (a manager may move a margin by at most 2 pp per change; a bigger change becomes a request the head approves; an analyst can preview but not apply). Changing `governance` is head-only. The "Signed in as" picker is a **demo identity, not authentication**: it sends `X-Acting-As`, anyone can pick anyone, and the server checks the role on every action. Real SSO is out of scope. A request with no header fails closed: it acts as the least-privileged role (analyst) and cannot apply anything. Limits are cumulative: a manager's net drift on a setting is measured from the last value set without a limit applying (the committed default, or a value the head set or approved), so repeated small steps cannot add up past it.
* **Change log** (SQLite `policy_changes`): every attempt, refused ones included, with who, role, source (prompt, form, undo, reset), the prompt, the structured diff, status (applied, pending_approval, refused, rejected, undone), the reason, the approver and the playbook hash before and after. Form edits and resets go through the same permission check and are logged. Undo is itself a checked, logged change that restores the previous values; it is refused (409) if a later change touched the same setting, and a change can be undone only once. Approving a request re-checks the playbook: if a value changed since the request was made it is closed as stale. "By N" rules are relative edits (`op: add`) resolved against the current value when the preview is built, and a preview is refused at apply time if the playbook moved under it. NaN and infinity are rejected everywhere. Growth is bounded: previews are rate limited per address, drafts are capped and expire after an hour, pending requests are capped per playbook, and the local log keeps `RULES_MAX_LOCAL_CHANGES` entries.
* **Public demo**: on a replay deploy rule changes work per visitor. Edits go to a private sandbox playbook and log keyed by the caller's address plus the browser's random `X-Visitor-Id` (kept 24 h, capped at `RULES_MAX_CHANGES_PER_VISITOR` log entries and `RULES_MAX_VISITORS` sandboxes), so nobody else's playbook, and none of the recorded runs, is affected. The five example prompts use recorded translations and cost nothing; free-form prompts need `PUBLIC_LIVE_FEATURES` to list `rules` and go through the public live budget.
* The engine's playbook hash (which approvals and recorded runs key on) deliberately ignores `governance`: changing who may edit a rule changes no number.

API: `POST /api/policy/propose`, `GET /api/policy/examples`, `GET /api/policy/changes`, `POST /api/policy/changes/{id}/apply|approve|reject|undo|discard`; `PUT /api/policy` and `POST /api/policy/reset` return `202` with the change when it needs approval and `403 change_refused` when the role may not make it.

## Bring your own vendor

`/try` lets anyone upload a SKU sheet (CSV or XLSX, up to 2 MB and 200 rows), optionally an application and up to 5 documents, pick a starter playbook
(pet, beauty, electronics) and get the same screening, verdict table, levers and verifier. One-click samples for beauty and electronics ship in
`data/samples/` with small market-data stubs; a category without market data reports **Needs data** with the reason rather than a guess.
The rules engine always runs and costs nothing ("Rules-only (no model calls)"). Model stages run only when allowed: a valid demo key, or the
caller's per-IP budget (`UPLOAD_LIVE_BUDGET_USD_PER_IP`), always under the global `MAX_SPEND_USD` cap; in mock mode a clearly labelled generic mock stands in.
Sandbox vendors are stored under `STATE_DIR` (a Volume path on Modal), expire after `UPLOAD_TTL_HOURS` (24) and are swept by a cleanup job.
Ops limits: `UPLOAD_MAX_ROWS`, `UPLOAD_MAX_SHEET_BYTES`, `UPLOAD_MAX_DOCS`, `UPLOAD_MAX_DOC_BYTES`, `UPLOAD_RATE_PER_HOUR`, `UPLOAD_MAX_ACTIVE`, `TRUST_FORWARDED_FOR`.

## Deploy

Prepared for Modal (backend, replay mode) and Vercel (frontend); no deployment is claimed here. Step by step, including the Modal secret and the post-deploy smoke
test (`make smoke URL=...`), in [scripts/deploy.md](scripts/deploy.md).

## Built during the hackathon

All code and data in this repository were created from October 26, 2026 onward, during the hackathon.

- First commit date: 2026-10-27
- Live golden runs: V001 to V004 recorded on 2026-10-27 against Muse Spark 1.3, Muse Image 1.0 and SAM 3.1 for about $1.83 of Meta credits in total (that includes an aborted first attempt, a repeated V002 recording and the SAM cut-out regeneration; the four final recordings are about $1.0). Recording times: V001 241 s, V002 258 s, V003 128 s, V004 23 s. No degraded (fell-back) events in any of them.
- What the live verifier actually caught (nothing scripted): whenever the first read of a certificate date disagreed with the re-read of the cropped region, the claim was **rejected** and not used. V001: FSSAI valid from "16 AUG 2022" vs re-read "10 AUG 2022". V002: GST valid from "01 APR 2023" vs "01 APR 2025", and valid until "31 MAR 2030" vs "01 MAR 2030". V003: GST valid from "01 APR 2021" vs "01 APR 202", and valid until "31 MAR 2030" vs "31 MAR 203" (the re-read came back truncated). In every case the first read matched the synthetic ground truth and the re-read was the wrong one: the verifier rejects a disagreement without deciding which read is right, so it was conservative, not lucky. No claim was self-corrected into agreement. Two more claims (V001 GST certificate dates) stayed unverifiable because the region was read only once.
- Synthetic data is generated by `data/generate.py` with seed 42
- No real company data is used

## Limitations and honest notes

- All vendors, SKUs, prices, competitors and reviews are synthetic.
- Replay mode serves recorded runs; it demonstrates the product, not live model behaviour. Each recording is a single live run per vendor, so the wording and the re-read noise are whatever that run produced.
- Where a vendor sheet omits cost, cost is inferred and labelled "inferred".
- The Launch stages (Marketing, JBP, PO) are intentionally thin.

## Repo map

```
backend/    FastAPI app, agents, metrics, verifier, fixtures, tests
frontend/   Next.js app (vendors board, vendor workspace)
data/       Synthetic data and generate.py (see data/README.md)
eval/       Measured eval (verifier, agent, injection) and its results
scripts/    deploy.md, smoke_deployed.sh and measure.py (make eval)
Makefile    setup, demo, test, lint, record, smoke, data and other targets
```

## Testing

```bash
make test   # backend pytest + frontend vitest
make lint   # ruff + eslint
```

`.github/workflows/ci.yml` defines the same checks plus gitleaks, but GitHub Actions is currently disabled for this account (billing), so CI has not run: results here come from running the commands locally.

## Troubleshooting

- **Port 8001 in use:** stop the other process, or override the backend port in `.env`.
- **"Backend unreachable" banner:** the backend is not running or is on a different port. Run `make demo` and check that http://localhost:8001 responds.

## License

MIT. See `LICENSE`.
