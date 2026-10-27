# CategoryOS

[![CI](https://github.com/Nandish3010/categoryos/actions/workflows/ci.yml/badge.svg)](https://github.com/Nandish3010/categoryos/actions/workflows/ci.yml)

An agentic category manager that decides whether to bet ₹X on a new vendor — which SKUs, at what terms — and proves every number.

**Live demo:** _coming Nov 1_

_GIF: demo walkthrough (placeholder, added Nov 3)_

Built for the Meta Global AI Developer Hackathon (indie track), Oct 26 - Nov 4, 2026.

## Try it in 60 seconds

```bash
git clone <repo-url> categoryos && cd categoryos
make setup
make demo
```

Then open http://localhost:3000/vendors/V001.

`make demo` runs in **replay** mode: it plays back recorded runs of the full pipeline (screen, decide, negotiate, catalog,
launch packet) with their original pacing. No API keys, no database, no network. Approve, override, reject and re-plan all
work on your session. `make dev` runs the same app in **mock** mode (the pipeline actually executes against canned model
fixtures, with a local SQLite database). Neither needs keys.

## What it does

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
- **The impact meter.** The app records how long a person actually spends reviewing each stage (from "ready for review" to approve) and counts their edits, then compares that with the playbook's by-hand baselines (`impact`, placeholders until you replace them). The vendor workspace has a per-vendor drawer; the vendors board has a team projection that says whether it is measured or a baseline estimate.

Negotiate is transcript-first: the vendor call is transcribed and the commitments are extracted into a gap table against the application. Voice is layered on top.

## Measured eval

`make eval` runs three checks and writes `eval/results/*.json`: the **verifier** against planted errors (digit
transposition, decimal shift, kg vs g, Rs vs paise, wrong row, wrong column, rounding beyond tolerance, spelled-out
numbers) with matched correct controls; the **extraction agent** through two models, graded by the verifier and the
self-correction loop; and **prompt injection** variants hidden in vendor text. It defaults to mock (free): the verifier
and injection checks run real code on synthetic data, the agent rows use scripted stand-ins. `--live` runs the models
(needs `MODEL_MODE=live`, keys, credits). The table below is injected by `scripts/measure.py` and always names its mode.

<!-- eval:start -->
**Mode: mock.** These numbers come from a mock run: the verifier and injection checks are real code on synthetic data, but the agent rows use scripted stand-ins for the models, so they are NOT measurements of Muse Spark. Seed 42, run 2026-10-27.

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

**Extraction agent** (160 tasks, mode: mock)

| Model | First-pass accuracy | Caught by verifier | Corrected on retry | Self-correction rate | Final accuracy | Silent errors | Cost | Latency / task |
|---|---|---|---|---|---|---|---|---|
| muse-spark-1.3 (model A) | 94.4% | 9 | 8 | 89% | 99.4% | 0 | n/a (mock) | n/a (mock) |
| Muse Spark Open via Baseten (model B) | 84.4% | 25 | 21 | 84% | 97.5% | 0 | n/a (mock) | n/a (mock) |

_Mock: scripted stand-ins with a fixed error profile replace the models. The loop, feedback, verifier and scoring are real; the error rates are parameters, not measurements. Cost and latency are not reported._

**Prompt injection** (30 variants hidden in vendor text, 30 look-alike benign texts)

| Detector | Injections caught | Benign texts wrongly flagged |
|---|---|---|
| Regex guard (playbook `screening.injection_patterns`) | 9/30 (30%) | 0/30 (0%) |
| Model | not run (mock) | not run (mock) |
| Regex + model | 9/30 (30%) | |
<!-- eval:end -->

## Meta models used

| Model | What it does here | Where (file) | Without it |
|---|---|---|---|
| `muse-spark-1.3` | Reasoning, extraction and narrative for all agents | `backend/app/agents/*` (planned) | No agent output; only deterministic metrics remain |
| `muse-spark-1.3-contributor` | Cheaper model for development iteration | `backend/app/llm.py` (planned) | Dev loops use the main model and cost more |
| Muse Spark Open via Baseten (`meta-models/muse-spark-open`) | SKU classification of messy vendor sheets | `backend/app/agents/catalog.py` (planned) | Falls back to a deterministic keyword classifier |
| `sam-3.1` | Packshot cutouts | `backend/app/agents/catalog.py` (planned) | Original packshot shown with a label |
| `muse-image-1.0` | Packshots and lifestyle images | `backend/app/agents/catalog.py`, `backend/app/agents/launch.py` (planned) | Catalog and launch cards have no generated imagery |
| `muse-voice-transcribe-1.0` | Transcribes the vendor call | `backend/app/agents/negotiate.py` (planned) | Uses the stored transcript fixture, with a banner |

## Architecture

```
Next.js (Vercel) --HTTP + SSE--> FastAPI (Modal) --> Meta Model API (OpenAI SDK, https://api.meta.ai/v1)
                                       |               muse-spark-1.3 / -contributor, sam-3.1, muse-image-1.0,
                                       |               muse-voice-transcribe-1.0
                                       +--> Baseten: meta-models/muse-spark-open (sheet classification)
                                       +--> deterministic metrics (pure Python over data/synthetic)
                                       +--> SQLite: vendors, runs, events, claims, approvals
```

The backend gateway (`app/llm.py`) switches between mock and live, tracks cost against a spend cap, and falls back to fixtures on failure. `app/metrics.py` computes per-SKU metrics; `app/verify.py` re-checks claims.

## Modes

| Mode | What it does | Keys needed | Cost |
|---|---|---|---|
| `mock` | Executes the pipeline against hand-written fixtures for every model call. Default for `make dev` and the tests. | None | Free |
| `replay` | Plays back recorded golden runs (`backend/fixtures/golden/runs/`) as ephemeral in-memory sessions with their original pacing (gaps capped at 1.5 s). Re-plan serves cached narratives for the presets 0, +2, +4 at the default MOQ; other lever values return `narrative_unavailable`. The lever/metrics endpoint stays live. Default for `make demo` and the public deploy. A golden run that fails its checksum, schema or metrics-hash check is served from the mock fixtures and flagged `degraded` in `GET /api/mode`. | None | Free |
| `live` | Calls the Meta Model API and Baseten for the stages in `LIVE_STAGES`; keyed routes need `X-Demo-Key`. | `MODEL_API_KEY`, `BASETEN_API_KEY` | Metered, capped by `MAX_SPEND_USD` |

Golden runs are produced by `make record` (runs the mock pipeline end to end and captures every event; deterministic).
To capture live runs later: `cd backend && MODEL_MODE=live RECORD=1 uv run python -m app.record --vendor V001`.

## Configuration

Only needed for live mode. Copy `.env.example` to `.env`.

| Variable | Purpose |
|---|---|
| `MODEL_API_KEY` | Meta Model API key |
| `MODEL_API_BASE_URL` | Meta Model API base URL |
| `BASETEN_API_KEY` | Key for Muse Spark Open on Baseten |
| `DEMO_KEY` | Server-side key that unlocks live calls on the public deploy |
| `MODEL_MODE` | `mock`, `live` or `replay` |
| `LIVE_STAGES` | Comma-separated stages that run live when mode is `live` |
| `MAX_SPEND_USD` | Hard cap on model spend; live calls are refused above it |

## Configure the playbook

Every rule a category manager would tune (margin targets per category, vendor-type and brand offsets, demand and overlap
thresholds, compliance documents and claim rules, negotiation requirements, catalog and launch rules, PO tax and lead
times, lever bounds, verifier tolerances, and the SKU taxonomy) lives in one file: `config/policy.yaml`. The backend reads
it everywhere, and the model prompts are rendered from it, so no rule exists only in English or only in Python.

* Edit it in the UI at `/rules` (Playbook), or by hand: UI edits go to `config/policy.local.yaml` (gitignored); the
  effective playbook is the defaults deep-merged with that file. "Reset" deletes the override (or one section or field).
* `GET /api/policy` returns the effective playbook, the defaults, which paths are overridden and a hash; `PUT /api/policy`
  takes a partial. A rule change changes the metrics hash, so stale approvals are refused. Replay mode is read-only.
* Nothing is pet-specific in code. `config/examples/beauty.yaml` and `config/examples/electronics.yaml` are complete
  alternative playbooks (taxonomy, margins, documents such as CDSCO or BIS, claim rules, attributes, GST) that prove the
  engine is vertical-agnostic. Copy one over `config/policy.local.yaml` to try it; the demo data stays pet.
* Market facts (units per SKU, price bands) stay in `data/synthetic/category_benchmarks.json`; ops settings (spend caps,
  rate limits, timeouts) stay in env.

## Deploy

Backend on Modal (replay mode), frontend on Vercel. Step by step, including the Modal secret and the post-deploy smoke
test (`make smoke URL=...`), in [scripts/deploy.md](scripts/deploy.md).

## Built during the hackathon

All code and data in this repository were created from October 26, 2026 onward, during the hackathon.

- First commit date: 2026-10-27
- Release tags: `v0.1-mock`, `v1.0-submission`
- Synthetic data is generated by `data/generate.py` with seed 42
- No real company data is used

## Limitations and honest notes

- All vendors, SKUs, prices, competitors and reviews are synthetic.
- Replay mode serves recorded runs; it demonstrates the product, not live model behaviour.
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

CI (`.github/workflows/ci.yml`) runs the backend (pytest, ruff), the frontend (eslint, tsc, vitest, build) and gitleaks on every push and PR.

## Troubleshooting

- **Port 8001 in use:** stop the other process, or override the backend port in `.env`.
- **"Backend unreachable" banner:** the backend is not running or is on a different port. Run `make demo` and check that http://localhost:8001 responds.

## License

MIT. See `LICENSE`.
