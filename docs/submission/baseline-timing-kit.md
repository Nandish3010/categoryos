# Baseline timing kit (about 1 hour)

Goal: replace the research estimates in `config/policy.yaml` `impact` with minutes you measured yourself, then set `baseline_status: measured`. Until then every figure stays labelled "estimate". Do not round to flatter the result.

## How to time honestly
1. Use one realistic vendor made of **synthetic files only**: use V001 in `data/synthetic/vendors/V001/` (about 12 SKUs, application, scans). No real vendor, price or employer data.
2. Stopwatch (phone). Start when you open the files, stop when the deliverable is ready to send/approve.
3. **By hand** means your normal tools (Excel, email, Google, a doc). Do the real task, not a rushed version, but keep scope identical to what CategoryOS produces (same output).
4. **With CategoryOS** means from opening the stage to pressing approve, including fixing anything you disagree with. The app's impact meter records this too; use whichever is larger.
5. **Do not count waiting** (vendor reply time, marketplace approval, model run spinner, lunch). Pause the stopwatch. Count only your active minutes.
6. Time each step once cold, don't repeat the same vendor by hand twice (you will be faster). Do the by-hand run first, with-tool run on a different day or different vendor of similar size if you can.
7. For per-SKU steps, time 3 SKUs and divide by 3.
8. Write down the date, vendor id, SKU count, and anything unusual.

## A. Per-vendor onboarding (one vendor of about 12 SKUs)
| Task | policy.yaml key | Research estimate (min) | By hand (measured) | With CategoryOS (measured) | Times per week |
|---|---|---|---|---|---|
| Document screening | `baseline_minutes.screening` | 45 | | | |
| Market research, per SKU | `baseline_minutes.market_research_per_sku` | 20 | | | |
| Shortlist and rationale | `baseline_minutes.shortlist` | 30 | | | |
| Negotiation prep / gap analysis | `baseline_minutes.negotiation_prep` | 60 | | | |
| Negotiation calls + notes | `baseline_minutes.negotiation_calls` | 110 | | | |
| Conditional-offer evaluation | `baseline_minutes.conditional_offer_eval` | 30 | | | |
| Catalog listing, per SKU | `baseline_minutes.catalog_listing_per_sku` | 25 | | | |
| Images / content, per SKU | `baseline_minutes.image_content_per_sku` | 10 | | | |
| Compliance checks, per SKU | `baseline_minutes.compliance_per_sku` | 5 | | | |
| Marketing / JBP draft | `baseline_minutes.marketing_jbp_draft` | 60 | | | |
| First PO draft | `baseline_minutes.first_po_draft` | 30 | | | |
| **Total (per 12 SKUs)** | | about 1,085 | | | vendors/month: |

Note: negotiation calls take the same wall time with the copilot; time only your prep and notes, as the estimate assumes about a 20% saving there.

## B. Recurring tasks (existing vendors)
| Task | policy.yaml key | Unit | Research estimate (min) | By hand (measured) | With CategoryOS (measured) | Times per week |
|---|---|---|---|---|---|---|
| Price-increase request | `recurring_minutes.price_increase_request` | per request | 90 | | | |
| Weekly review / MIS pack | `recurring_minutes.weekly_review_pack` | per week | 240 | | | |
| Vendor scorecard | `recurring_minutes.vendor_scorecard` | per vendor | 75 | | | |
| PO chase | `recurring_minutes.po_chase` | per late PO | 15 | | | |
| Fill-rate reconciliation | `recurring_minutes.fill_rate_reconciliation` | per vendor | 45 | | | |
| Catalog fix | `recurring_minutes.catalog_fix_per_sku` | per SKU | 12 | | | |
| Promotion / event plan | `recurring_minutes.promotion_event_plan` | per event | 480 | | | |
| QBR / JBP deck | `recurring_minutes.qbr_jbp_deck` | per vendor per quarter | 600 | | | |
| Competitor price sweep | `recurring_minutes.competitor_price_sweep` | per day | 30 | | | |
| Inventory ageing review | `recurring_minutes.inventory_ageing_review` | per week | 180 | | | (module not built: leave by-hand only) |

Time the Run pages: `/run` (MIS), `/run/price-requests`, `/run/pos`, `/run/catalog`, `/run/promotions`, `/run/price-watch`.

## C. Weekly time split (keep a 1-week diary, or estimate from your calendar)
Fill your own % of a typical week (each column sums to 100). Estimates in brackets are `category_manager_pct` / `category_executive_pct`. `Saved %` = your honest view of the share of that task's time CategoryOS saves, informed by section A/B.

| Activity (key under `impact.workload`) | CM % (est) | CM % (yours) | CE % (est) | CE % (yours) | Saved % (est) | Saved % (yours) |
|---|---|---|---|---|---|---|
| `new_vendor_onboarding` | 14 | | 9 | | 45 | |
| `assortment_planning` | 7 | | 5 | | 30 | |
| `price_increase_requests` | 6 | | 4 | | 50 | |
| `pricing_margin` | 6 | | 5 | | 25 | |
| `catalog_create_qc` | 3 | | 18 | | 55 | |
| `content_images` | 2 | | 6 | | 45 | |
| `promotions` | 9 | | 7 | | 35 | |
| `jbp_qbr` | 6 | | 2 | | 50 | |
| `po_replenishment` | 5 | | 10 | | 55 | |
| `inventory_health` | 4 | | 5 | | 40 | |
| `vendor_scorecards` | 3 | | 3 | | 65 | |
| `compliance` | 2 | | 4 | | 40 | |
| `reporting_mis` | 8 | | 9 | | 65 | |
| `meetings` | 14 | | 5 | | 5 | |
| `competitor_monitoring` | 3 | | 4 | | 60 | |
| `reviews_triage` | 2 | | 3 | | 50 | |
| `other` | 6 | | 1 | | 0 | |
| **Total** | 100 | 100 | 100 | 100 | | |

## D. Where the numbers go (`config/policy.yaml`, section `impact`)
- Section A times (with-tool column is not stored; the app measures it live): `impact.baseline_minutes.<key>` for the 11 keys in the table.
- Section B times: `impact.recurring_minutes.<key>`.
- Team shape: `impact.team.category_managers`, `category_executives`, `work_hours_per_week` (default 45), `vendors_onboarded_per_month` (from "times per week" x 4.33), `typical_skus_per_vendor`.
- Section C: `impact.workload.<activity>.category_manager_pct`, `.category_executive_pct`, `.saved_pct`. Keep each role's column summing to 100.
- `impact.max_review_minutes`: set to the longest review you consider real (a gap longer than this is counted as this many minutes).
- When all of the above are your own measurements: set `impact.baseline_status: measured` (leave it at `research_estimate` if any part is still guessed). Edit in the UI at `/rules` (writes `config/policy.local.yaml`) or paste into `config/policy.yaml`.
- Leave `impact.target_reduction_pct` (33.3) alone; it is the goal the projection is compared against, not a result.
- Then fill the video placeholders: `{{BASELINE_HOURS_PER_VENDOR}}` = section A by-hand total / 60; `{{BASELINE_MINUTES_WITH_COS}}` = section A with-tool total.
