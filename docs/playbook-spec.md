# CategoryOS playbook (policy) — design spec

Goal: every business rule a category manager would tune lives in ONE human-readable playbook,
is loaded by the backend everywhere it is used (no hardcoded duplicates), is rendered into the
LLM prompts (no English-only rules), and is viewable + editable in a Rules page in the UI.

## Files
- `config/policy.yaml` — committed DEFAULTS, heavily commented, grouped by stage. Source of truth.
- `config/policy.local.yaml` — gitignored OVERRIDES written by the UI. Effective policy = deep-merge(defaults, local).
  Lists replace (not merge). "Reset to defaults" deletes the local file (or one section of it).
- Market FACTS stay in `data/synthetic/category_benchmarks.json` (avg_monthly_units_per_sku, price bands, gaps, sku_count).
  POLICY (target_pct, min_pct, payment_terms_days) moves out of benchmarks into the playbook. Remove those keys
  from benchmarks + generate.py so there's one source.
- Ops settings (spend caps, rate limit, timeouts, token prices, SSE heartbeat, replay gaps) stay in env/config.py — NOT playbook.
- Modal image must include `config/` (add_local_dir) — check backend/modal_app.py.
- Add `.gitignore` entry for `config/policy.local.yaml`.

## Schema (pydantic model `Policy` in backend/app/policy.py; yaml keys = these)
```yaml
version: 1
onboarding:
  required_application_fields: [company_name, brand_name, contact_name, contact_email, city, years_in_business, categories, documents, proposed_terms, vendor_type]
  required_terms: [margin_offered_pct, payment_terms_days, moq_units, marketing_support_inr, launch_discount_pct, returns_policy]
  vendor_types:            # used for margin overrides; application.json gets a new `vendor_type` field
    national_brand: {label: "National brand", target_offset_pp: -3}
    d2c_brand:      {label: "D2C brand",      target_offset_pp: 0}
    importer:       {label: "Importer / distributor", target_offset_pp: 0}
    private_label:  {label: "Private / white label", target_offset_pp: 8}
screening:
  documents:   # one row per document type
    - {type: GST, blocking: true, categories: all}
    - {type: PAN, blocking: true, categories: all}
    - {type: FSSAI, blocking: true, categories: [dog dry food, dog wet food, cat dry food, cat wet food, treats]}
    - {type: Trademark, blocking: false, categories: all}
    - {type: Certificate of Incorporation, blocking: false, categories: all}
  absent_document_counts_as_missing: true   # FIX: a required doc not listed at all is now "missing"
  expiry_warning_days: 60
  fail_on: [blocking_document, prompt_injection, medical_claim]   # deterministic guard; medical_claim now enforced in code
  claim_rules:   # shared by Screen AND Catalog compliance (single list, replaces catalog.py:50-52 regexes + prompt examples)
    - {type: medical_claim, severity: high, patterns: [...current catalog regex alternatives as plain regex strings...], examples: ["cures arthritis", "treats ear infections"]}
    - {type: unverifiable_superlative, severity: medium, patterns: [...], examples: [...]}
    - {type: unsubstantiated_claim, severity: medium, patterns: [...], examples: ["boosts immunity", "vet formulated"]}
  injection_patterns: [...current screen.py:13-18 regexes...]
  data_quality_flags: [mrp_missing, pack_missing, cost_missing, hsn_missing]   # what the agent flags as missing_data
research:
  demand_min: 0.40
  overlap_max: 0.60
  freight_pct: 0.04
  neutral_review_score: 0.6
  keyword_match_min_coverage: 0.7
  fit_weights: {margin: 0.4, demand: 0.3, overlap: 0.2, review: 0.1}
  below_min_margin_action: negotiate   # negotiate | reject   (default keeps today's behaviour; reject makes min_pct bite)
  moq_flag_factor: 2.0                 # flag if MOQ > factor x shortlisted monthly units
margins:
  categories:      # base targets per category
    dog dry food: {target_pct: 27, min_pct: 20, payment_terms_days: 30}
    ... (all 9 categories, values copied from current benchmarks: target, min, typical_payment_terms_days)
  brands: {}        # optional per-brand offset, e.g. "Highland Paws": {target_offset_pp: 0, note: "..."}
  # effective target = category.target_pct + vendor_type.target_offset_pp + brand.target_offset_pp + lever offset
  # same offsets apply to min_pct
negotiation:
  margin_ask: target            # target | min — what the gap table requires
  payment_terms_days: category  # "category" = use margins.categories[c].payment_terms_days, or a number
  payment_longer_is_better: true
  moq_max_factor: 2.0
  marketing_min_pct_of_order: 0.10
  launch_discount_min_pct: 5
  defect_return_min_days: 7
catalog:
  title_max_chars: 80
  bullets: {min: 3, max: 5}
  description_sentences: {min: 2, max: 3}
  required_attributes: {default: [pack, mrp], dog dry food: [life_stage, breed_size, protein, grain_free, pack_g, mrp], ...}  # per category, used in prompt AND validated (missing -> compliance flag missing_label_info medium)
  fssai_label_categories: [dog dry food, dog wet food, cat dry food, cat wet food, treats]
  hero_sku_count: 3
  image_sizes: {packshot: 1024x1024, lifestyle: 1792x1024, campaign: 1792x1024}
launch:
  launch_discount_days: 30
  launch_week_days: 7
  sell_through_review_day: 30
  platform_funded_discount_max_pct: 0     # cap on our share of launch discount (now coded; model value clamped)
  jbp_top_skus: 5
  jbp_sections: [Overview, Targets, Investments, Promo calendar, Commitments and next steps]
po:
  gst_rate_default: 0.18
  gst_rate_by_category: {}     # e.g. {"toys": 0.12}
  lead_days: {confirmed: 2, shipped: 5, received: 12}
  simulated_delay_days: 3       # demo only
  number_format: "PO-{vendor}-{date}"
levers:
  margin_offset: {min: -10, max: 10, step: 1}
  moq: {step: 50, max_factor: 2}
verifier:
  tolerances: {pct: 0.01, inr: 1.0, units: 0, score: 0.5, ratio: 0.005, qty: 0}
```
Every key gets a one-line YAML comment saying what it does and which stage uses it.

## Backend
- `backend/app/policy.py`: pydantic `Policy` (strict, extra=forbid, sensible bounds e.g. 0<=pct<=100, demand_min 0..1),
  `load_policy()` cached, `save_overrides(partial_dict)` (validate merged result BEFORE writing), `reset(section|None)`,
  `policy_hash()`. On change: clear metrics `build_base` cache + any lever caches.
- Replace every constant/hardcode listed in the inventory with policy reads. Keep `constants.py` only for non-policy
  things (STAGE_META, PHASES, ROUND_DP, ALLOWED_VENDORS). Unify V00[1-4] regex duplicates onto ALLOWED_VENDORS.
- Prompts (prompts.py, prompts_exec.py) are RENDERED from policy: blocking docs list, claim rule types/examples,
  fail rule, data-quality flags, title length, bullets, description sentences, required attributes per category,
  JBP sections. No rule exists only in English anymore.
- Margin target breakdown: SkuMetrics gets `target_breakdown: {category_pct, vendor_type_pp, brand_pp, lever_pp}`.
- Fixes bundled in:
  1. Negotiation required margin honours vendor_type/brand/lever offsets and `margin_ask`.
  2. V002 transcript buyer turns: turn 3 says "our treats target is 35 percent" (instead of "needs at least 28"); turn 7
     must not claim "45 days as standard" — make it consistent with the 21-day treats policy (e.g. "We need at least
     21 days"). Do NOT change vendor turns (their quotes are verified). Update both call_transcript.json and .txt and generate.py if it writes them.
  3. Absent required documents count as missing (category-aware: FSSAI only for food/treats). V003 (toys) must stay unblocked.
  4. medical_claim in fail_on enforced deterministically in screen.py.
  5. Returns parser accepts "60-day ... window" style as well as "within N days".
  6. Lever API bounds from policy.levers (keep API hard limits as outer safety).
  7. Model's platform-funded discount clamped to policy cap.
- Add `vendor_type` to each synthetic application (V001 d2c_brand, V002 d2c_brand, V003 importer, V004 d2c_brand) via generate.py + regenerate data (seed 42; verify only intended diffs).
- API:
  - `GET /api/policy` → `{policy, defaults, overridden_paths: [..dotted..], hash, editable: bool, schema_hints}` where
    schema_hints = per dotted path {label, help, unit, min, max, step, used_in:[stage ids]} (generated from Field metadata) so the UI can render forms without hardcoding.
  - `PUT /api/policy` body = partial policy (deep-merged into overrides). 422 with {code, problem, cause, fix} on invalid. 
  - `POST /api/policy/reset` body `{section?: str}`.
  - editable = effective_mode != "replay". Writes require demo key ONLY when a DEMO_KEY is configured (same pattern as other keyed routes); in replay mode PUT/reset return 403 {code: "policy_read_only"}.
  - Policy hash included in /api/mode and in metrics_hash input so a rule change invalidates stale approvals.
- Tests: policy load/merge/validate/reset; every moved rule still produces the same 4-vendor outcomes with defaults
  (V001 7 list/0 neg/5 rej; V002 0 list/4 neg/6 rej; V003 0 list; V004 fails screening); a changed demand_min / category
  target / vendor_type offset changes verdicts; absent-doc rule; medical claim fail; returns parser; prompts contain
  policy values (e.g. change title_max_chars -> prompt text changes); API GET/PUT/reset/read-only. Mock golden runs: if outputs legitimately change, re-record with mock mode only (`make record` with MODEL_MODE=mock — NO paid calls) and explain.
- docs/api-contract.md + README: "Configure the playbook" section.

## Frontend
- New page `/rules` ("Playbook"), linked from the vendors board header and the workspace top bar.
- Left: section nav in stage order (Onboarding, Screening, Research, Margins, Negotiation, Catalog, Launch, PO, Levers, Verifier).
  Each section card shows which stages use it (chips).
- Field rendering driven by `schema_hints`: number (with unit, min/max/step), toggle, enum select, string-list chips
  (add/remove), and two tables: margin categories (editable target/min/payment days per row) and vendor types / brands
  (add/remove rows, offset pp). Show "effective target = category + vendor type + brand + lever" explainer.
- Overridden fields show an "Edited" dot + per-field "reset". Section-level "Reset section". Sticky save bar:
  "N unsaved changes · Discard · Save". Errors from 422 shown inline under the field (problem/fix).
- Read-only mode (editable=false): inputs disabled, banner "Public demo: the playbook is read-only. Run locally to edit."
- After save: toast "Playbook saved — new runs and the lever use these rules"; invalidate lever caches client-side.
- SKU verdict table: Target cell gets a tooltip showing target_breakdown.
- Also fix board/banner copy: vendor whose screening failed shows chip "Failed screening" (bad) and the Decide banner
  says "Do not onboard: screening failed" instead of "Recommend: negotiate"; vendor whose majority SKUs are reject
  shows "Reject" chip (V003). Derive from latest run screen result + counts; add vitest.
- Use existing components/tokens (Chip, PanelHeader, Banner, Slider, DataTable). Dark theme tokens from DESIGN.md. vitest for: hints-driven field render, dirty tracking + save payload is minimal partial, read-only disables inputs.

## Deal evaluator knobs (negotiation)

Conditional offers ("15% base, +20% marketing support if you sell 2,000 units in 90 days") are valued by `backend/app/deals.py`
with these playbook keys (all under `negotiation`, used by the Negotiate stage; schema hints are generated like every other field):

| Key | Default | Meaning |
|---|---|---|
| `forecast.ramp_by_month` | `[0.5, 0.75, 0.9, 1.0]` | share of steady-state monthly units a new listing sells in month 1, 2, 3...; the last value repeats |
| `forecast.cv` / `forecast.cv_by_category` | `0.45` / `{}` | forecast uncertainty (lognormal coefficient of variation), optionally per category |
| `forecast.sku_correlation` | `0.5` | share of demand noise common to all SKUs |
| `forecast.mc_draws` / `forecast.seed` | `20000` / `42` | Monte Carlo size and the fixed seed (same inputs, same probability) |
| `contingent.min_probability` | `0.6` | a conditional bonus counts only when P(earn it) is at least this |
| `contingent.value_basis` | `risk_adjusted` | or `guaranteed_only`: count no conditional bonus at all |
| `contingent.dead_stock_horizon_days` / `dead_stock_writeoff_pct` | `180` / `100` | unsold stock treated as dead after this long; share of its cost lost |
| `contingent.counter_window_days` | `[30 ... 365]` | windows tried when proposing a longer or shorter condition window |
| `contingent.threshold_round_{units,inr,pct}` | `10` / `5000` / `1` | counter thresholds are rounded down to these steps |
| `cost_of_capital_pct_annual` | `14` | prices paying earlier for a discount |
| `inventory_carrying_pct_monthly` | `2` | prices holding extra stock for a bigger-MOQ discount |
| `verifier.tolerances.pts` | `0.05` | tolerance when a claim is a value in margin points |
