# CategoryOS run API contract

Backend: FastAPI (`backend/app/main.py`). All errors share one shape, whether raised by validation,
auth or the agents: `{"code", "problem", "cause", "fix", "run_id"}` (`run_id` is null unless the request sent
`X-Run-Id`). Pydantic request validation failures are the usual FastAPI `422`.

## Stages

Eight stage ids, in order: `intake`, `research`, `shortlist`, `negotiate`, `catalog`, `marketing`, `jbp`, `po`.

| Agent | Stage id it reports on | Notes |
|---|---|---|
| Screen | `intake` | deterministic document check, then a tool-calling model pass |
| Decide | `research` | one engine run for the verdict table; its `shortlist` mirror is created with it |
| (mirror) | `shortlist` | mirrors research's verdict table: `review` until research is approved, then `done` |
| Negotiate | `negotiate` | runs after `approve(research)`; `done` (no approval) |
| Catalog | `catalog` | runs after Negotiate; `review`, `needs_approval: true` |
| Launch packet | `marketing`, `jbp`, `po` | ONE agent after `approve(catalog)`; `marketing` and `jbp` end `done`, `po` ends `review` with `needs_approval: true` |

## Run flow

```
POST runs -> intake -> research (review) + shortlist (review)          ... `done` event
approve(research, metrics_hash)  -> shortlist done; negotiate -> catalog (review)   ... `done` {phase:"execute"}
approve(catalog, metrics_hash)   -> marketing, jbp, po (review)                       ... `done` {phase:"launch"}
approve(po, metrics_hash)        -> po done
```

Approving returns immediately with the approved StageResult; the next phase runs in the background and ends with its own
`done` TraceEvent whose payload is `{phase: "execute"|"launch"}`. The SSE stream closes after each `done`, so after an
approve reconnect with `Last-Event-ID: <last seq>` (or poll `GET /api/runs/{id}`). Approving a stage that is already
`done` is a no-op (it never re-runs the next phase). `approve` on a `locked` stage (for example V004, or after a reject)
is `409 stage_locked`. Re-plan is refused (`409 stage_not_reviewable`) once negotiate has started.
For `catalog` and `po`, `narrative_hash == metrics_hash ==` the approved research hash; a different hash is `409 stale_approval`.
The Launch packet needs `catalog` to be approved with that hash.

Status FSM: `pending` -> `running` -> `review` (needs a human) | `done` | `failed` | `locked`.
A passed Screen ends `done` (it needs no approval). Decide ends `review` with `needs_approval: true`;
approving it makes it `done`. If Screen fails, `intake` is `failed` and every later stage is `locked`.

### StageResult

```json
{
  "stage": "research",
  "status": "pending|running|review|done|locked|failed|degraded",
  "summary": "string",
  "data": {},
  "needs_approval": false,
  "locked_reason": null,
  "claims": [],
  "metrics_hash": null,
  "narrative_hash": null
}
```

`claims` are `Claim` objects as returned by `GET /api/vendors/{id}/claims` (`origin` is `engine`, `model_extraction` or
`vision_extraction`; `status` is `verified|rejected|unverifiable`). A `model_extraction` claim the verifier rejected and
the agent was asked to re-read also carries `attempts: [{attempt, value, status, reason?, recomputed?}]`, oldest first
(`attempt` 0 is the agent's first answer). `status` is the last attempt's: `verified` with more than one attempt is
"caught, then corrected"; `rejected` with more than one is "unresolved" after `verifier.max_self_corrections` retries.
Claims that were never rejected have `attempts: []`.

### Self-correction

When the verifier rejects a `model_extraction` claim (Decide: a cost or MRP read off the sheet; Negotiate: a commitment;
Catalog: an MRP or pack quantity), the agent gets one feedback message per rejected claim, for example
`Claim V001:HP-D01:cost:extracted rejected: you said ₹965.50; the evidence cites sheet row 2 'Cost to Us'. Verifier: sheet
cell 'Rs. 956.50' parses to 956.5, claim says 965.5. Re-read and correct.`, and may answer again
(`{"fixes": [{claim_id, value, row?, header?, turn?, transcript_quote?}]}`) up to the playbook's
`verifier.max_self_corrections` (default 2; 0 turns it off). A corrected answer is verified exactly like the first. A
corrected Decide extraction is written back into the narrative (the sentences that quoted the wrong number now quote the
corrected one); a claim still wrong after the last retry stays `rejected`, its sentence is struck as before (Decide), the
commitment drops out of the gap table (Negotiate) or the sheet value replaces it (Catalog). Decide's `data` gains
`self_correction: {max, corrected: [claim_id], unresolved: [claim_id]}`, and an `extractions[]` item that was corrected
carries `original_value` and `attempts`.

A `vision_extraction` claim is a number or date a vision model read off a scanned document. Its `evidence` is
`{doc, page, bbox: [x0, y0, x1, y1] (fractions of the page), crop_sha256, raw_value (the page read, as printed),
reread_value (the second, independent read of the cropped region), as_of, sha256 (of the page file), parser_version}`.
`source_ref.file` is `vendors/<VID>/docs/<page file>`. The verifier checks that the page file is the one that was read, that
the box lies on the page and its pixels hash to `crop_sha256`, that `raw_value` parses to the claimed number and that
`reread_value` says the same: `verified` when both reads agree, `rejected` when they differ (the reason quotes both),
`unverifiable` when there is no second read. Date claims carry the days from `as_of` to the printed date (`metric`
`doc_date:<kind>.<field>`); other claims use `doc_value:<kind>.<field>` with the field's unit.

`intake` `data`: `{decision: "pass"|"fail", reasons[], risk_flags: [{type, quote, severity}], injection_detected,
followup_questions[], documents: {documents[], problems[], blocking}, guards[], mode}`. When it fails,
`locked_reason` is set on the stage itself and on every later stage (prefixed `Screening failed:`).

`research` `data`: `{headline, rationale_per_sku: [{code, verdict, why, edited_by_human?, original_verdict?, note?}],
counter_offer: {terms: [{term, ask, current?, fallback?, sku_code?, rationale}], email_draft},
extractions: [{sku_code, field: "cost"|"mrp", value, row, header, claim_id, status, sheet_value}],
struck: [{claim_id, sku_code, field, claimed_value, sheet_value, reason, where, sentence}],
verdict_corrections[], overrides?, lever: {target_margin_pct_offset, moq}, summary (DecideSummary),
verification: {total, verified, rejected, unverifiable}, replanned: bool, mode}`.

- `struck` lists the narrative sentences removed because a model extraction was rejected by the verifier
  (`where` is `rationale:<code>`, `headline`, `email_draft` or `term:<name>`; `sentence` is the removed text, or
  null if no sentence cited the number). Rejected claims stay in `claims`.
- `metrics_hash` is the hash of the metrics (`GET /decide/metrics`) the result was computed from.
  `narrative_hash` is the metrics hash the narrative was generated for; at creation both are equal.
  If the user moves the levers, the UI's current hash differs from `narrative_hash`: the narrative is stale and
  approval is refused until a re-plan.
- `verdict` is always the engine's verdict (a disagreeing model verdict is replaced and logged in
  `verdict_corrections`), unless a human override changed it (`edited_by_human: true`).

### `shortlist` `data`

`{verdict_table: [{code, name, verdict, engine_verdict, edited_by_human, margin_pct, target_pct, fit_score, est_gmv,
alloc_units, reasons[]}], counts: {list, negotiate, reject, needs_data}, shortlisted, approved, source_stage: "research"}`.
`verdict` includes human overrides.

### `negotiate` `data`

The canonical transcript JSON is the source of truth. If `vendors/<VID>/call.wav` exists and the negotiate stage is live,
the call is also transcribed (`POST /v1/asr/transcribe`) and diffed against the canonical text; the ASR text is never trusted.

```json
{"gap_table": [{"term": "margin_pct|payment_days|moq|marketing_inr|launch_discount_pct|returns", "label", "unit": "pct|days|units|inr",
   "direction": "higher|lower", "application": 17, "offered": 21, "required": 35, "gap": -14,
   "status": "met|gap|not_stated", "turn": 4, "quote": "...", "claim_id": "...", "verification": "verified|rejected|..."}],
 "application_terms": {}, "required": {"category", "margin_pct", "margin_min_pct", "payment_days", "moq", "marketing_inr", "launch_discount_pct", "returns"},
 "commitments": [{"term", "offered", "transcript_quote", "turn", "claim_id", "status", "reason"}],
 "refusals": [{"term", "transcript_quote", "turn", "note", "quote_verified"}],
 "counter_offer": {"asks": [], "email_draft": ""},
 "transcript": {"turns": [{"turn", "speaker", "text"}], "asr_text": null, "similarity_pct": null, "changes": [], "audio_hours": null} | null,
 "transcript_source": "canonical|asr", "negotiated_skus": [], "verification": {"total", "verified", "rejected", "unverifiable"}, "mode"}
```

- `gap = offered - required`; `status` is judged in `direction` (for `moq` lower is better). `required` comes from the Decide
  engine: the category target margin of the main negotiate category, the benchmark payment terms, `2 x` forecast monthly units
  for MOQ, 10% of the first-order retail value for marketing, a 5% launch discount and a 7-day defect-return window.
- Each commitment is a `model_extraction` claim (metrics `commit_margin_pct`, `commit_payment_days`, `commit_moq`,
  `commit_marketing_inr`, `commit_launch_discount_pct`, `commit_returns`). The verifier checks that `transcript_quote` appears
  verbatim in the canonical transcript at `turn` and states the committed number. A rejected commitment is kept in
  `commitments`/`claims` but is not counted: its gap-table row becomes `not_stated`.
- `transcript_source` is `"asr"` when a voice transcription was produced (shown next to the canonical text), else `"canonical"`.
- No negotiate SKUs: `done`, summary `No negotiation needed`, `gap_table: []`. No call transcript on file (V003): a
  deterministic gap table from the application terms, every row `not_stated`, `transcript: null`.
- A conditional or tiered offer ("X% if you sell Y units in N days") is not a commitment; it is valued by the deal
  evaluator below, in `data.deals`.

#### `data.deals` (deal evaluator)

Present when the call transcript or `application.proposed_terms.additional_terms` holds something to read (V002's
contingent litter offer, V001's tiered back margin); absent otherwise. The model (`muse-spark`, task `deals_<VID>`) only
copies offers into `DealTerm`s: `{id, kind: base|conditional|tiered|rebate|free_goods|exclusivity|payment_for_discount|
moq_for_discount|sell_or_return|price_protection, term: margin_pct|back_margin_pct|discount_pct|marketing_pct|marketing_inr|
free_goods_pct|returnable_pct|exclusivity_months|price_protection_days, value, unit, condition?: {metric: units|gmv_inr|
sell_through_pct, threshold, window_days, scope[]}, tiers?: [{threshold, value}], scope[], base_of?, days?, units?, quote,
turn, source: transcript|application}`. For an application term, `turn` is the 1-based index into `additional_terms`.
Every number of a term (value, threshold, window, tier values, days, units) is a `model_extraction` Claim
(`deal_term_<field>`): its quote must appear verbatim in that turn / additional term and state the number, or the whole
term is sent back to the agent first (self-correction, `verifier.max_self_corrections`, task `deals_<VID>__fix<n>`) and, if still wrong, dropped into `rejected_terms` and never valued. `app/deals.py` then values the verified terms in Python:

```json
{"decision": "reject_structure|accept|needs_human|not_assessable|none", "headline": "...",
 "assessments": [{"term_id", "kind", "term", "label", "source", "turn", "quote",
   "decision": "accept|reject_structure|needs_human|not_assessable", "call": "plain-English verdict",
   "reasoning": [], "base_pts", "face_pts", "expected_bonus_pts", "counted_bonus_pts", "expected_pts", "guaranteed_pts",
   "counted_pts", "required_pts", "shortfall_pts", "probability": 0.0, "net_pts": null,
   "tiers": [{"threshold", "bonus_pts", "incremental_pts", "probability", "counted"}],
   "distribution": {"metric", "window_days", "mean", "p10", "p50", "p90", "threshold", "bins": [33 edges], "density": [32]},
   "counters": [{"kind": "threshold|window|scope|convert_to_base", "text", "threshold?", "window_days?", "scope?",
     "probability?", "required_base_pts?", "uplift_pts?", "fair_conversion_pts?", "counted_pts_after", "meets_requirement"}],
   "recommended_counter": 0, "base_term_id": "t1", "base_assumed": false}],
 "base_terms": [DealTerm], "rejected_terms": [{"id", "label", "reasons": []}],
 "assumptions": {"min_probability", "value_basis", "ramp_by_month", "cv", "cv_by_category", "sku_correlation", "mc_draws",
   "seed", "cost_of_capital_pct_annual", "inventory_carrying_pct_monthly"},
 "talk": {"talk_track", "email_paragraph", "source": "model|rules", "struck": []} | null,
 "claim_status": {"<claim id>": "verified|rejected|unverifiable"}, "verification": {"total", "verified", "rejected", "unverifiable"}, "mode"}
```

- Demand: per SKU, the Decide engine's `est_monthly_units` x the new-listing ramp (`negotiation.forecast.ramp_by_month`),
  lognormal noise (`forecast.cv`, optionally per category), a shared factor (`forecast.sku_correlation`) and a fixed-seed
  Monte Carlo (`forecast.mc_draws`, `forecast.seed`): `probability` is P(metric >= threshold) and `p10/p50/p90` are quantiles
  of the metric over the window. Tiers each carry their own probability.
- Value, in margin points: `expected = base + sum(p_i x bonus_i)`, `guaranteed = base`. `counted` replaces each bonus by 0
  when `p_i < negotiation.contingent.min_probability` (or all of them under `value_basis: guaranteed_only`). `required_pts`
  is the target margin of the SKUs involved. Marketing in rupees converts to points over the first-order GMV; discounts
  and free goods convert by landed cost / price. Payment-for-discount trades subtract `cost_of_capital_pct_annual` x days
  brought forward; MOQ-for-discount trades subtract carrying cost (`inventory_carrying_pct_monthly`) and dead-stock risk;
  exclusivity is `needs_human` with an opportunity-cost note and is never auto-accepted.
- Decision: `accept` when `counted_pts >= required_pts`, else `reject_structure` with `counters`, in this order:
  `threshold` (largest target with P >= min_probability, rounded down), `window` (shortest window that makes the vendor's
  own target likely), `scope` (sell-through only) and `convert_to_base` (guaranteed uplift = required - base, with the
  risk-adjusted bonus as the fair anchor). `recommended_counter` is the first that meets the requirement.
- Claims (`origin: engine`, recomputed by the verifier from a self-contained `source_ref.key`
  `<VID>?offset=..&moq=..#<json of terms and context>`): `deal_probability` (`column: tier:<i>`), `deal_percentile`
  (`p10|p50|p90`), `deal_pts` (`base|expected|counted|required|net`), `deal_counter` (`threshold:<i>`, `uplift:<i>`).
  `Claim.unit` gains `pts` (tolerance `verifier.tolerances.pts`).
- `talk` is the agent's call and email paragraph written from the figures only; a sentence stating a number the evaluator
  did not produce is removed and listed in `struck`. `null` when every offer is acceptable. Recommended counters are also
  appended to `counter_offer.asks`.

### `catalog` `data`

```json
{"skus": [{"code", "name", "verdict", "raw_row": {"<header>": "<cell>"}, "normalized": {"mrp", "cost", "cost_source", "selling_price",
   "pack", "pack_normalized", "pack_detail", "category", "subcategory", "flags"},
   "classification": {"rules": {"category", "subcategory"}, "model": {"category", "subcategory", "valid"} | null,
     "agreement": true|false|null, "note": null | "Classified by rules" | "Model label differs; kept the rules' classification"},
   "copy": {"sku_code", "title" (<=80), "bullets" (3-5), "description", "attributes": {}, "compliance_flags": [{"rule", "text", "severity", "source": "model|rules"}], "generated_by": "model|rules"},
   "attribute_checks": [{"claim_id", "status", "reason"}], "corrections": [{"attribute", "claimed", "sheet", "claim_id"}],
   "images": {"packshot": "/api/assets/...", "cutout": "/api/assets/..." | "unavailable", "cutout_note"?, "lifestyle": url | null,
     "image_source": "live|placeholder|mixed", "sources": {}, "errors"?: []},
   "hero": false}],
 "classifier_agreement_pct": 71.4 | null, "hero_skus": [], "image_mode": "live|placeholder", "verification": {}}
```

- Classification: the taxonomy rules are the truth. Baseten (`muse-spark-open`, prompted for JSON over the catalog label set) is
  validated against it; disagreement keeps the rules' label. An unusable reply means `Classified by rules` and
  `classifier_agreement_pct: null`.
- Compliance rules: `medical_claim` (high), `unverifiable_superlative`, `unsubstantiated_claim`, `missing_label_info`
  (shelf life, net quantity, ingredients, FSSAI licence for food).
- `attributes.mrp` and the pack quantity (`pack_g`/`pack_ml`/`pack_pc`) are `model_extraction` claims (metrics `mrp`, `pack_qty`)
  verified against the sheet cell; a rejected value is replaced by the sheet value and logged in `corrections`.
- The three SKUs with the highest `est_gmv` are `hero` and get a `lifestyle` image. A failed or disabled SAM cutout is the
  string `"unavailable"` (the UI shows the packshot with a "cutout unavailable" label). Mock and replay images are Pillow
  placeholders labelled `image_source: "placeholder"`.

### `marketing` `data`

`{campaign_name, copy, discount_ask: {brand_funded_pct, our_pct, rationale}, image: {url, image_source}, corrections[],
brand_funded_marketing_inr, mode}`. `brand_funded_pct` is always the committed launch discount (a differing model value is
replaced and logged in `corrections`).

### `jbp` `data`

`{markdown, targets: {shortlisted_skus, est_monthly_gmv_inr, est_monthly_units, blended_margin_pct, first_order_units,
first_order_cost_inr, payment_days}, investments: {brand_funded_marketing_inr, launch_discount_pct, launch_discount_days, source},
promo_calendar: [{name, start, end}], mode}`.

### `po` `data`

`{po_number, vendor_id, date, lines: [{code, name, units, unit_cost, cost_source, line_total}], subtotal, gst_rate: 0.18, gst,
grand_total, gst_note, payment_days, terms_source: {term: "negotiation"|"application"}, moq_source, approved_moq,
timeline: [{step: "raised|confirmed|shipped|received", status, planned_date, expected_date, delay_days, alert?}], alerts[],
status: "raised", verification}`. Units come from the engine allocation (at the vendor's verified MOQ commitment when there
is one, else the approved MOQ). `claims` holds `po_total` (subtotal) and `po_grand_total`, both recomputed by the verifier.
The timeline is simulated, with dates derived from the run's `demo_today` and one deterministic delay alert at `shipped`.

## TraceEvent

```json
{
  "seq": 7,
  "run_id": "run_ab12cd34ef",
  "t_rel_ms": 412.5,
  "type": "stage_started|tool_call|model_call|claim_checked|claim_rejected|self_correction|claim_verified|claim_unresolved|stage_result|degraded|error|done",
  "stage": "intake|...|null",
  "model": "muse-spark-1.3|null",
  "latency_ms": 12.3,
  "cost_usd": 0.0,
  "payload": {}
}
```

`seq` is 1-based, strictly increasing per run (continues across a re-plan). `t_rel_ms` is milliseconds since the run
started. Payloads:

| type | payload |
|---|---|
| `stage_started` | `{stage}` |
| `tool_call` | `{tool, args, result_summary, deterministic?}` (`deterministic: true` for engine/document steps that are not model-chosen) |
| `model_call` | `{task, mode: "mock"|"replay"|"live", input_tokens, output_tokens, tool_steps}`; `model`, `latency_ms`, `cost_usd` set on the event |
| `claim_checked` | `{claim: Claim}` with its final `status` and `reason` |
| `claim_rejected` | `{claim, attempt}`: the verifier rejected the agent's answer (`attempt` 0 is its first answer, later ones are retries) |
| `self_correction` | `{attempt, of, claim_ids[], feedback[], answered, note?}`: the agent was told what the source says; `answered: false` means no corrected answer was available |
| `claim_verified` | `{claim, attempt}`: the corrected answer passed |
| `claim_unresolved` | `{claim, attempts}`: still rejected after the last retry |
| `stage_result` | a full `StageResult` |
| `degraded` | `{reason}` (replay fell back to a mock fixture) |
| `error` | `{code, problem, cause, fix, run_id}` |
| `done` | `{}` (first phase), `{replan: true}` after a re-plan, `{phase: "execute"|"launch"}` after an approval phase; the stream closes after each |

## Routes

`X-Demo-Key` is required only where noted. "When live" means at least one stage's effective mode is `live`
(`GET /api/mode` -> `stage_modes`); in `mock` and `replay` these routes are open.

### `POST /api/vendors/{id}/runs` -> `202 {"run_id": "run_..."}`
Starts Screen, then Decide if Screen passed, as a background task. Demo key when live. `404 unknown_vendor`.

### `GET /api/vendors/{id}/runs/latest` -> `{"run_id": "run_..."|null}`

### `GET /api/runs/{run_id}`
```json
{"run_id": "...", "vendor_id": "V001", "mode": "mock", "created_at": "2026-10-27T10:00:00.000+00:00",
 "stages": {"intake": StageResult, "research": StageResult, "...": "all 8 ids always present"},
 "impact": RunImpact}
```
Untouched stages are `{"status": "pending"}` StageResults. `404 run_not_found`.

`impact` is the impact meter's block for this run. Human time is recorded, not assumed: the clock starts the first time a
stage reaches `review` and stops at its first approval (re-plans do not restart it), and each gap is counted up to
`impact.max_review_minutes`. The three review steps cover the work behind them: `research` (screening, market research,
shortlist), `catalog` (negotiation prep and follow-up, catalog listings, image briefs) and `po` (marketing brief, JBP,
PO raise and follow-up).
```json
{"run_id", "vendor_id", "mode", "baseline_status": "research_estimate|measured", "n_skus", "tasks": [{"task", "label", "gate",
  "minutes", "per_sku", "count", "total_minutes"}],
 "gates": [{"stage": "research|catalog|po", "label", "status": "measured|pending", "baseline_minutes", "review_seconds"|null,
   "counted_minutes"|null, "capped", "overrides", "replans", "edits"}],
 "baseline_minutes", "baseline_measured_minutes", "human_minutes", "reduction_pct"|null, "measured_gates", "total_gates",
 "complete", "basis": "measured|research_estimate", "edits", "overrides", "replans", "max_review_minutes"}
```
`reduction_pct` compares the human minutes with the baseline of the *reviewed* steps only (`null` before any approval);
`edits` are verdict overrides plus re-plans. `baseline_status` mirrors the playbook: the shipped baselines are research estimates (about 1,085 min for a 12-SKU vendor).

### `GET /api/impact`
The team rollup. Every number is built from the playbook's `impact` section, which ships **research estimates, not
measurements** (`docs/research/category-manager-workload.md`; `baseline_status: research_estimate`). The team is
`impact.team` (default 1 category manager + 2 category executives, 45 h week); `impact.workload` gives each task's share of
each role's week and the share of it automation saves; `impact.modules` lists the modules (`shipped` or `not_built`) and
`impact.coverage` says which share of which task each one takes over, so a new module registers there.
```json
{"basis": "measured|research_estimate", "measured_runs", "partly_measured_runs", "baseline_status",
 "in_scope_pct", "saved_pct", "potential_saved_pct", "target_pct", "meets_target", "team_hours_per_month",
 "hours_saved_per_month", "roles": [{"role", "label", "headcount", "in_scope_pct", "saved_pct"}],
 "modules": [{"key", "label", "status": "shipped|not_built", "in_scope_pct", "saved_pct", "tasks": [{"task", "label", "in_scope_pct"}]}],
 "onboarding": {"typical_skus", "baseline_hours_per_vendor", "human_share_pct"|null, "saved_pct_basis", "vendors_per_month",
   "demand_hours_per_month", "team_hours_on_task_per_month"},
 "formula", "team": {...}, "mode", "vendors": [{"vendor_id", "run_id", "baseline_minutes", "human_minutes", "measured_gates", "complete", "reduction_pct"}]}
```
(a) `in_scope_pct` is the share of the team's week that shipped modules touch; (b) `saved_pct` is the share of the week saved;
(c) `modules` lists every module with its status (`saved_pct` of a `not_built` module is what it would add). Per task:
`share of the week x share of the task a shipped module covers (rows on one task add up, capped at 100) x share of that time
saved`; the team is headcount-weighted over the two roles. A module marked `measured_from_runs` (onboarding) uses the
measured review reduction (1 - recorded human review time / by-hand baseline, over fully reviewed runs) instead of the
table's `saved_pct` once at least one run is fully reviewed; then `basis` is `measured`. With the shipped defaults the
numbers reproduce the report: about 19% in scope, about 9% saved, about 34% if every module were built.

### `GET /api/runs/{run_id}/events` -> `text/event-stream`
```
id: 7
event: trace
data: {TraceEvent JSON}

: ping

```
- Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- A comment line `: ping` is sent every 15 s of silence (`SSE_HEARTBEAT_S`).
- `Last-Event-ID: n` replays stored events with `seq > n`, then continues live. A new connection without the header
  starts from seq 1, so a late subscriber gets the whole run.
- The stream ends after an event of type `done`. The browser `EventSource` cannot send headers, so clients should use
  a fetch stream; no key is needed on this route.
- After a re-plan, its events (ending in another `done`) are appended to the same run's log.

### `POST /api/runs/{run_id}/stages/{stage}/approve`  body `{"metrics_hash": "..."}`
`200` StageResult with `status: "done"`, `needs_approval: false`. Approving `research` starts Negotiate + Catalog and approving
`catalog` starts the Launch packet (see Run flow). `409 stage_locked` for a locked stage. `409`
`{"code": "stale_approval", "problem", "cause", "fix"}` if `metrics_hash != narrative_hash`.
`409 stage_not_reviewable` if the stage is not `review`/`done` or has no narrative (e.g. `intake`, locked stages).
`404 unknown_stage|run_not_found`.

### `POST /api/runs/{run_id}/stages/{stage}/override`  body `{"sku_code", "verdict", "note"?}`
`verdict` is `list|negotiate|reject|needs_data`. `200` StageResult; the SKU's `rationale_per_sku` entry gets
`edited_by_human: true`, `original_verdict`, `note`, and `data.overrides[sku_code]` records it. The narrative hash is
unchanged. `404 unknown_sku`, `409 stage_not_reviewable`, `422` for a bad verdict.

### `POST /api/vendors/{id}/decide/replan`  body `{"run_id", "target_margin_pct_offset" (-20..20), "moq" (0..20000)}`
Re-runs Decide for those lever values and replaces the run's `research` result. `200` StageResult with
`narrative_hash == metrics_hash ==` the hash of those levers and `data.replanned: true`. In mock/replay the fixture's
narrative is reused but verdicts, the headline and the counter-offer SKU list are recomputed from the metrics so the
text is consistent. Demo key when live. `409 stage_locked` if Screen failed, `409 stage_not_reviewable` while Decide
is running; `404 run_not_found` (also when the run belongs to another vendor).

### `POST /api/vendors/{id}/reject`  body `{"run_id", "reason"}`
`200 {"run_id", "vendor_id", "status": "rejected", "reason"}`. `research` becomes `failed` (`data.rejected: true`) and
`shortlist` .. `po` become `locked` (`locked_reason: "Vendor rejected: ..."`).

### `POST /api/admin/reset`  (demo key, always)
`200 {"ok": true}`. Empties the store and in-memory run state. Idempotent.

### `GET /api/docs/{vendor}/{file}` -> `image/png|jpeg` or `application/pdf`
A vendor's uploaded document or page image, as listed in `data/synthetic/vendors/<VID>/docs/manifest.json`. Anything else
(`manifest.json`, `truth.json`, traversal, unknown vendor or file) is `404 asset_not_found`. Open (no key).

### `GET /api/assets/{vendor}/{file}` -> `image/png`
Cached catalog and campaign images. `file` is `<SKU code>-packshot|cutout|lifestyle.png` or `campaign.png`; anything else
(traversal, other extensions, unknown vendor) is `404 asset_not_found`. In mock/replay a missing file for a real SKU is drawn
as a labelled placeholder on demand. Open (no key).

## Bring your own vendor (sandbox)

Sandbox vendors are `U-` plus 8 lowercase alphanumerics (`^(V00[1-9]|U-[a-z0-9]{8})$` is the id pattern). They live under `STATE_DIR` for
`UPLOAD_TTL_HOURS` (24), never in the repo, and then read as `404 unknown_vendor`. Every existing vendor route works for them
(`/api/vendors/{id}`, `decide/metrics`, `claims`, `runs`, `replan`, `docs`); runs cover Screen and Decide, approving research locks the
later stages. Each vendor uses the playbook of its chosen starter (`pet` = the effective playbook, `beauty`, `electronics` = `config/examples`).

### `GET /api/uploads/options`
Starters (`id, label, vertical, vendor_types, required_documents, document_kinds, has_sample, has_market_data`), `limits`
(`sheet_mb, rows, documents, document_mb, ttl_hours`), and the `llm_mode` / `mode_label` a new upload would get.

### `POST /api/uploads` (multipart) -> `201 SandboxInfo`
Fields: `starter` (pet|beauty|electronics), `sample` (beauty|electronics: use the bundled sample instead of a sheet), `sheet` (csv/xlsx),
`application` (json file) or the form fields `company_name, brand_name, vendor_type, categories, margin_offered_pct, payment_terms_days,
moq_units, marketing_support_inr, launch_discount_pct, returns_policy, pitch`, and parallel lists `documents` / `doc_kinds` / `doc_declares`.
Content is sniffed, not trusted by name. Errors use the usual `{code, problem, cause, fix}`: `upload_invalid` 422, `upload_too_large` 413,
`upload_wrong_type` 415, `rate_limited` 429, `sandbox_full` 503, `unknown_sample` 404.
`SandboxInfo`: `id, starter, llm_mode (rules_only|mock|live), mode_label, expires_at, ttl_remaining_s, application_provided, market_stubs,
sku_count, warnings[], documents[{name, kind, title, status (read|not_read), reason}], url`. `GET /api/vendors/{id}` returns the same under
`sandbox` (plus `skus_without_market_data`).

Model stages: `rules_only` means no model call at all (free, always available); `mock` is the server's canned stand-in; `live` needs a valid
`X-Demo-Key` or the caller's per-IP daily budget (`UPLOAD_LIVE_BUDGET_USD_PER_IP`, default 0.50), and the global `MAX_SPEND_USD` cap always applies.
SKUs whose category has no benchmark (or a vendor with no search-demand rows) get verdict `needs_data` with an explanation instead of a guess.

### `GET /api/uploads/samples/{name}/sku_sheet.csv`, `GET /api/vendors/{id}/export.csv`
The sample sheet, and the verdict table as CSV with every text cell neutralised against spreadsheet formulas.

## Scanned documents

Playbook section `documents` decides which document kinds are read (`kinds`, each read in `intake` or `catalog`), which fields
(`fields`, typed `text|date|pct|inr|qty|number`, `critical` ones are cropped and read again) and which pairs are compared
(`cross_checks`: a document field against the application, the SKU sheet or the listing copy, with a severity and a
tolerance in the field's unit). `catalog.label_panel_prompt` is the phrase SAM 3.1 uses to find a label's nutrition and claims
panel. Per document: muse-spark-1.3 (vision) extracts the fields with boxes; for a label SAM segments the panel and that crop is
read again, otherwise the critical fields are cropped by their own boxes; every numeric or date field becomes a
`vision_extraction` claim; the cross-checks run on the verified readings.

`intake` `data.scanned_documents` and `catalog` `data.scanned_documents` (both `{enabled: false, ...}` when the playbook turns
the pipeline off or the vendor filed nothing of that stage):

```json
{"enabled": true,
 "documents": [{"file", "kind", "label", "title", "declares": "FSSAI"|null, "sku_code"|null, "url": "/api/docs/V002/<file>",
   "pages": [{"page", "file", "url", "width", "height"}], "legible", "error"|null, "notes", "mode",
   "panel": {"page", "bbox"|null, "prompt", "source": "sam-3.1"|..., "crop_sha256"}|null,
   "expiry": {"valid_until", "days", "state": "valid|expiring_soon|expired", "as_of"}|null, "injection": [],
   "fields": [{"name", "label", "type", "raw", "value", "reread"|null, "page", "bbox", "confidence", "sku_code"|null,
     "status": "verified|rejected|unverifiable|read|conflict|low_confidence|unreadable", "reason"|null, "claim_id"|null}]}],
 "findings": [{"id", "check", "label", "severity", "status": "match|mismatch|unreliable|injection", "doc", "doc_label", "page",
   "bbox", "field", "field_label", "sku_code"|null, "document_value", "other_label", "other_value", "other_source": {},
   "claim_id", "claim_status", "message"}],
 "summary": {"documents", "fields", "claims", "verified", "rejected", "unverifiable", "mismatches"}}
```

- `unreliable` means the page read and the re-read of the crop disagree, so the value was not compared. `injection` means
  text addressed to an AI reviewer was found inside a document; it is ignored and Screen fails the vendor.
- Intake: the scanned certificate is ground truth over the declared status. `data.documents.documents[]` entries gain
  `source: "scan"` and `declared_valid_until` when a scan decided the date and state (a declared "valid" with a scan that says
  "expired" fails screening as a blocking problem). Mismatches add `document_mismatch` risk flags and follow-up questions, a
  certificate expiring or expired on the scan adds `document_expiring_soon` / `document_expired`, an unreadable page adds
  `document_unreadable`. The stage `claims` hold the `vision_extraction` claims.
- Catalog: each SKU with a label gets `label_check: {doc, title, url, pages, panel, error, fields, rows: [{field, label,
  label_value, sheet: {value, status, source, check}|null, listing: {...}|null, status: "match|mismatch", severity,
  unreliable, claim_id, claim_status, page, bbox}]}` (`null` without one). A mismatch adds a `label_mismatch` compliance flag
  and the playbook's claim rules also run over the text printed on the label (flags have `source: "label"`).

Trace: `tool_call` `read_documents` and `cross_check_documents` (deterministic), `model_call` with `task` `doc_extract`,
`segment_panel`, `doc_reread_panel` or `doc_reread_fields` (and `document`), then `claim_checked` per vision claim.

## Live call (negotiation copilot)

A call is a session in process memory (like replay sessions: gone on restart, at most 50). One pipeline serves every call:
audio chunk (live) or canonical turn (simulate) -> transcription -> a turn -> incremental extraction on a vendor turn
(`muse-spark`, task `copilot_<VID>_t<n>`, output `TurnExtraction {commitments, refusals, deal_terms}`) -> every quote verified
verbatim against the call's own turns -> gap table and deal evaluator recomputed -> next ask -> SSE.

| Route | Notes |
|---|---|
| `POST /api/vendors/{id}/call` body `{mode: "simulate"\|"live", speed?: 0.25..20}` -> `202 {call_id, mode}` | `simulate` streams the canonical transcript (V002; others `422 no_call_script`) with realistic pacing through the same pipeline from the mock fixtures, free in mock and replay (demo key only when some stage is live). `live` needs live mode (`409 live_call_unavailable` otherwise) and ALWAYS the demo key. |
| `POST /api/vendors/{id}/call/chunks` multipart `call_id`, `speaker: buyer\|vendor\|auto`, `audio` (16 kHz mono 16-bit WAV, about 6 s) -> `{turn, state}` | live calls only (`409 call_not_accepting_input` on a simulation). `415 unsupported_audio` without a RIFF/WAVE header, `413 chunk_too_large` above `CALL_CHUNK_MAX_BYTES`. Transcribes with `muse-voice-transcribe-1.0` (`POST {base}/asr/transcribe`, existing `media.transcribe`). |
| `POST /api/vendors/{id}/call/turns` `{call_id, speaker, text}` -> `{turn, state}` | a typed line through the same pipeline (live calls) |
| `POST /api/vendors/{id}/call/end` `{call_id}` -> snapshot | ends the call. A live call's transcript becomes the canonical transcript for the vendor (in process), so Negotiate verifies commitments against it. |
| `GET /api/vendors/{id}/call/{call_id}` | `{call_id, vendor_id, mode, ended, turns, state, last_seq, spend_usd}` |
| `GET /api/vendors/{id}/call/{call_id}/events` | SSE, `event: call`, `id` = seq, `Last-Event-ID` resumes; closes after `ended` |

Errors keep the typed shape: `call_not_found` 404, `call_ended` 409, `call_budget_exceeded` 429 (the per-call spend budget,
config `CALL_BUDGET_USD`, default 2.00; it is config, not playbook), plus the codes above.

SSE event `{seq, call_id, type, t_ms, payload}`: `started {mode, state, budget_usd}`, `turn {turn: {turn, speaker, text, source: simulated|asr|typed}}`,
`extraction {turn, model, mode, cost_usd, latency_ms}`, `state {state, changed: {gap_terms[], deal_ids[]}, turn}`, `error {code, problem, cause, fix, turn?}`,
`ended {turns, canonical, spend_usd, state}`. `state` is shaped like the Negotiate stage's `data` (`gap_table`, `commitments`, `refusals`, `required`,
`application_terms`, `transcript.turns`, `deals` as in `data.deals` without a talk track, `verification`) plus
`next_ask: {kind: reject_conditional|hold|gap|ask_term|done|listen, line, reason, term, deal_id?}` and `spend_usd`.
`next_ask` comes from the playbook rules and the engine's numbers (no model): a conditional offer that fails the deal evaluator
comes first ("Don't accept: <0.1% chance"), then the gap with the largest shortfall (for margin, trading the vendor's wish for
faster payment when the application asks for it, priced at `negotiation.cost_of_capital_pct_annual`).

## Other routes (unchanged)

`GET /health`, `/api/stages`, `/api/mode`, `/api/vendors`, `/api/vendors/{id}`,
`/api/vendors/{id}/decide/metrics`, `/api/vendors/{id}/claims`, `/api/ledger` (demo key).

## Playbook

All business rules live in `config/policy.yaml` (committed defaults) plus `config/policy.local.yaml` (UI overrides,
gitignored). Effective playbook = deep-merge(defaults, overrides). Nothing is pet-specific in code; `config/examples/`
holds beauty and electronics playbooks. Replay mode ignores local overrides and is read-only.

### Routes

| Route | Notes |
|---|---|
| `GET /api/policy` | The full shape below. Always open. |
| `PUT /api/policy` | Body is a NESTED PARTIAL playbook. Dicts merge key by key; lists and scalars replace; a `null` value for a key of a dict-table (`margins.categories`, `margins.brands`, `onboarding.vendor_types`, `catalog.required_attributes`, `catalog.image_prompts.segmentation`, `po.gst_rate_by_category`, `negotiation.forecast.cv_by_category`) deletes that key. Returns the full GET shape. |
| `POST /api/policy/reset` | Body `{section?: string}`; `section` is a top-level section (`research`) or any dotted path (`research.demand_min`). No body or `{}` resets everything. Returns the full GET shape. |

Writes: `403 {code: "policy_read_only"}` in replay mode; otherwise they need `X-Demo-Key` only when `DEMO_KEY` is
configured (`403 demo_key_required` without it). Invalid input is `422` with the usual error shape plus the dotted
field `path` of the first problem and the whole list: `{code: "policy_invalid", problem, cause, fix, run_id, path, errors: [{path, message}]}`.
Nothing is written when validation fails. `GET /api/mode` also returns `policy_hash`.

Lever bounds come from `levers`: `target_margin_pct_offset` outside `levers.margin_offset.{min,max}` or `moq` above
`levers.moq.max_factor x` the vendor's proposed MOQ is `422 lever_out_of_range` (the Query limits of -20..20 and 0..20000 stay as the outer safety).
A changed playbook changes `policy_hash`, which is part of every `metrics_hash`, so approvals made under old rules are refused (`409 stale_approval`).

### GET /api/policy

```json
{
  "policy": { "...": "effective playbook, same keys as config/policy.yaml" },
  "defaults": { "...": "committed defaults, same shape" },
  "overridden_paths": ["research.demand_min", "margins.categories"],
  "hash": "1a77e883d0ccbaab",
  "editable": true,
  "schema_hints": { "<dotted.path>": { "...": "see below" } }
}
```

`overridden_paths`: dotted paths whose effective value differs from the default. Tables and lists are listed as a whole
(`margins.categories`, never `margins.categories.treats`). `editable` is false in replay mode.

### schema_hints

Keyed by dotted path, one entry per field (and per section, kind `section`, whose `used_in` is the stage chips for the
section card). Every entry has `label`, `help`, `kind`, `used_in` (stage ids from `/api/stages`), and optionally `unit`
(`%`, `pp`, `days`, `x`, `ratio`, `chars`, `units`), `min`, `max`, `step`, `integer`, `options`. `kind` is one of
`number | bool | enum | string_list | table | text | section`. One example per kind:

```json
{
  "research.demand_min": {"kind": "number", "integer": false, "label": "Minimum demand", "help": "A SKU below this demand percentile is rejected.", "min": 0, "max": 1, "step": 0.05, "used_in": ["research", "shortlist"]},
  "screening.absent_document_counts_as_missing": {"kind": "bool", "label": "Absent counts as missing", "help": "...", "used_in": ["intake"]},
  "research.below_min_margin_action": {"kind": "enum", "options": ["negotiate", "reject"], "label": "Below-floor action", "help": "...", "used_in": ["research", "shortlist"]},
  "onboarding.required_terms": {"kind": "string_list", "options": ["margin_offered_pct", "payment_terms_days", "moq_units", "marketing_support_inr", "launch_discount_pct", "returns_policy"], "label": "Terms compared in negotiation", "help": "...", "used_in": ["negotiate"]},
  "business.retailer": {"kind": "text", "label": "Retailer", "help": "...", "used_in": ["intake", "research", "shortlist", "negotiate", "catalog", "marketing", "jbp", "po"]},
  "research.fit_weights": {"kind": "section", "label": "Fit score weights", "help": "Must sum to 1.", "used_in": ["research"]},
  "margins.categories": {
    "kind": "table", "shape": "dict", "label": "Category margins", "help": "...", "used_in": ["research", "shortlist", "negotiate"],
    "columns": [
      {"key": "name", "label": "Name", "kind": "text"},
      {"key": "target_pct", "kind": "number", "integer": false, "label": "Target margin", "unit": "%", "min": 0, "max": 95, "step": 0.5},
      {"key": "min_pct", "kind": "number", "integer": false, "label": "Minimum margin", "unit": "%", "min": 0, "max": 95, "step": 0.5},
      {"key": "payment_terms_days", "kind": "number", "integer": true, "label": "Payment terms", "unit": "days", "min": 0, "max": 365, "step": 1}
    ]
  },
  "screening.documents": {
    "kind": "table", "shape": "list", "label": "Documents", "used_in": ["intake"],
    "columns": [
      {"key": "type", "kind": "text", "label": "Document"},
      {"key": "blocking", "kind": "bool", "label": "Blocking"},
      {"key": "categories", "kind": "string_list", "allows_all": true, "label": "Applies to"}
    ]
  }
}
```

Tables: `shape: "dict"` is a mapping keyed by name (the first column, `key: "name"`, is the dict key; the remaining columns are
the row's fields; if the only other column is `value` the row is a bare value); `shape: "list"` is an ordered list of rows with the
listed columns. Dict tables are PUT as nested partials (null deletes a row); list tables are PUT whole. A column can itself
be a table (`taxonomy.categories[].subcategories`). `allows_all: true` on a `string_list` means the value may be the string `"all"` instead of a list.
`negotiation.payment_terms_days` is `kind: "text"` and accepts the word `category` or a number of days.

Sections (top-level keys of `policy`, in stage order): `business`, `onboarding`, `screening`, `taxonomy`, `research`, `margins`,
`negotiation`, `catalog`, `launch`, `po`, `levers`, `verifier`. Rows: `margins.categories.<name>` is `{target_pct, min_pct, payment_terms_days}`;
`onboarding.vendor_types.<key>` is `{label, target_offset_pp}`; `margins.brands.<brand>` is `{target_offset_pp, note}`;
`levers.margin_offset` is `{min, max, step}`; `levers.moq` is `{step, max_factor}`.
Vertical-agnostic sections: `taxonomy` (`categories[{name, patterns[], subcategories{name: patterns[]}, approximate_as?}]`,
`fallback_category`, `segments[{name, values{value: patterns[]}}]`; names may contain `{segment}` placeholders), `research.keyword_matching`,
`screening.claim_rules[].categories` (scope: `"all"` or a list), `catalog.label_licences`, `catalog.label_checks`, `catalog.image_prompts`.

### SkuMetrics additions

`SkuMetrics.target_breakdown = {category_pct, vendor_type_pp, brand_pp, lever_pp}`, all in PERCENT / percentage points, the
same unit as `margins.categories.*.target_pct` (so `27` means 27%). `target_pct` (a 0 to 1 fraction, clamped to 0..0.95) equals
`(category_pct + vendor_type_pp + brand_pp + lever_pp) / 100`. The floor shifts by `vendor_type_pp` and `brand_pp` only (not the lever).
The negotiate stage's `required` adds `margin_breakdown` (the same four numbers for the dominant negotiate category).

## Replay mode (`MODEL_MODE=replay`)

`POST /api/vendors/{id}/runs` creates an ephemeral in-memory session (no database writes) that re-emits the recorded
golden run (`backend/fixtures/golden/runs/<VID>.json`) over SSE, re-stamping `seq` / `t_rel_ms` on the session clock and
capping recorded gaps at 1.5 s; `model_call` payloads report `mode: "replay"`. Approve, override, reject and re-plan act on
the session only. Re-plan returns the recorded narrative for the presets `target_margin_pct_offset` in {0, 2, 4} at the
vendor's default MOQ; anything else is `422 {"code": "narrative_unavailable", "problem": "Narrative available in live mode",
"fix": "Use a preset (0, +2, +4) or run live"}`. `GET .../decide/metrics` stays live and deterministic. Sessions live in
process memory (capped at 200) and vanish on restart: `GET /api/runs/{id}` is then `404 run_not_found`.

`GET /api/mode` also returns `degraded: bool` and, in replay, `replay.vendors: {id: "ok" | <reason>}`. On startup each
golden run is checked (sha256 sidecar, `schema_version`, `parser_version`, pydantic models, `meta.metrics_hash` against the
current engine); a vendor that fails is served from the mock fixtures through the normal pipeline and flagged degraded.

## Run: existing vendors (`/api/ops/*`)

Weekly review and PO follow-up for existing vendors (ids `E001` to `E006` in the synthetic data; unrelated to the V00x applicants).
All numbers are computed in Python (`app/ops/metrics.py`, `app/ops/pos.py`); the agent (stage `ops`, tasks `review_mis`,
`review_emails`, `po_replies`, `po_drafts`, fixtures under `fixtures/mock/ops` and `fixtures/golden/ops`) only reads, explains,
prioritises and drafts. Every number it writes is a claim with a source under `ops/` that `app.verify.verify_claim` hands to
`app.ops.verify`: engine claims are recomputed, vendor-reply extractions (`reply_eta_days`, `reply_qty`) are checked against the
reply text and go through the self-correction loop. Playbook: `operations` (thresholds, anomaly rules, escalation ladder); the
modules `weekly_review_mis` and `po_followup` are registered in `impact.modules` / `impact.coverage`.

| Route | Returns |
|---|---|
| `GET /api/ops/review[?inject=1]` | category summary, vendor scorecards, anomalies, ranked actions, `mis_markdown`, vendor-review `drafts`, `claims`, `verification`, `unclaimed_numbers`, `trace`, `impact_coverage` |
| `GET /api/ops/pos[?inject=1]` | PO tracker rows (status, `days_overdue`, `risk`, `stockout_days`, `rung`), `readings` (stance, commitments with verbatim `quote`, verifier status, `corrected`), `ladder`, `ledger`, follow-up `drafts`, `claims`, `trace` |
| `GET /api/ops/vendors/{id}` | one vendor's scorecard with SKU rows, anomalies, actions, email draft, POs, readings, claims |
| `GET /api/ops/outbox[?kind=]` | queued drafts; `simulated: true` |
| `POST /api/ops/outbox/{id}/approve` `{body?}` | marks the draft `sent_simulated` (nothing is sent). `409 draft_has_unverified_numbers` if the text still states a rejected number; `409 draft_not_pending` |
| `POST /api/ops/outbox/{id}/reject` `{note?}` | `rejected` |
| `GET /api/ops/impact` | `impact_coverage` for both modules (playbook registration, units done, manual minutes replaced) |
| `POST /api/ops/reset` | demo key; clears caches and the outbox |

Errors are the usual `{code, problem, cause, fix}`: `unknown_ops_vendor`, `unknown_po`, `unknown_draft`, `draft_not_pending`,
`draft_has_unverified_numbers`, `ops_data_missing`, `unknown_ops_metric`. In live mode the GET routes need the demo key.

## Price requests (Run: existing vendors asking to raise prices)

The model reads a vendor's email and revised price list (`negotiate` stage, tasks `price_request_<id>`, `__fix<n>`, `price_request_reply_<id>`);
every cost, date and sweetener number carries a verbatim quote that is checked and self-corrected; Python decides per SKU
(`backend/app/pricereq.py`); a person approves the reply (sending is simulated). Percent fields are percent numbers (`4.0` = 4%).
Data: `data/synthetic/price_requests/` (generated by `data/generate_price_requests.py` from the ops vendors E001-E006; competitor
prices in `competitors.csv`). Playbook section: `price_requests`.

| Route | Returns |
|---|---|
| `GET /api/price-requests` | `{requests: [{id, vendor_id, brand, received_at, sender, subject, submitted, status}]}` (no model call) |
| `POST /api/price-requests` `{vendor_id, email, price_list?, sender?, subject?, received_at?}` | adds a request to the in-memory inbox (`201`). Reading it needs the model: mock mode has a fixture only for PR-001 to PR-003 |
| `GET /api/price-requests/{id}` | `request`, `email`, `price_list`, `reason`, `effective_date`, `evaluation`, `deals` (sweeteners as DealEvaluator assessments), `reply {subject, body, source, struck}`, `claims`, `verification`, `rejected`, `trace`, `mode`, `status` |
| `POST /api/price-requests/{id}/approve` `{role, email_body?, note?}` | `approved` with `sent.simulated: true`. `403 approval_tier_too_low` if `role` ranks below the required tier; `409 price_request_decided` |
| `POST /api/price-requests/{id}/reject` `{role, note?}` | `rejected` |

`evaluation`: `lines[]` (per SKU: `old_cost`, `new_cost`, `pct_change`, `effective_pct`, `current_margin_pct`, `new_margin_pct`, `needed_retail`,
`gap_if_passed_pct`, `volume_change_pct`, `elasticity_risk`, `justified`, `notice_days`, `decision` = `accept | accept_partial | pass_through |
delay | delist | needs_review`, `then_decision`, `counter_pct`, `counter_cost`, `counter_basis`, `ask_effective_date`, `reasons`, `scenarios`),
`sweeteners[]`, `decision` (most serious line), `approval {pct, asked_pct, tier, asked_tier, reasons, matrix}`, `counter_offer`,
`impact` (GMV and margin deltas over `horizon_days` if we absorb, pass on, or follow the decision), `justification`, `assumptions`.
Errors: `price_request_not_found`, `price_request_unreadable`, `price_request_invalid`, `approval_tier_too_low`, `price_request_decided`.
