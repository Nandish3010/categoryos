import type { PlanDecisionResult, PromoList, PromoPlan } from "@/lib/promotions";

/**
 * TRIMMED copies of real mock-mode responses of GET /api/ops/promotions, GET /api/ops/promotions/festive and
 * POST /api/ops/promotions/festive/approve. Rows, vendors, claims and trace are cut to the planted cases; `totals` keep
 * the full-plan numbers (24 SKUs) so the stat row matches the real page.
 * Planted: GW-03 stock-up PO, PL-02 capped by stock with a deep_option, PL-01/PL-02 cannibalising pair, BK-04 left out,
 * E001 reject_structure offer (P = 0.0359), E003 corrected reading (first read 53%, verified 35%), E005 declined.
 */

const PLAN = {
  "event": {
    "id": "festive",
    "name": "Festive Sale",
    "start": "2026-11-06",
    "end": "2026-11-12",
    "days": 7,
    "traffic_lift_pct": 10.0,
    "banner_slots": 3,
    "days_away": 11
  },
  "as_of": "2026-10-26",
  "mode": "mock",
  "degraded": false,
  "totals": {
    "planned_skus": 24,
    "excluded_skus": 12,
    "gmv_inr": 1706453.6161,
    "units": 6675.9902,
    "incremental_margin_inr": 35820.4562,
    "funding_ask_inr": 139702.1196,
    "stock_up_inr": 25850.0,
    "stock_up_units": 200,
    "margin_unfunded_pct": 0.137,
    "margin_at_ask_pct": 0.2189,
    "capped_by_stock": 3,
    "stock_up_pos": 3
  },
  "rows": [
    {
      "sku_code": "GW-01",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "name": "Oatmeal Pet Shampoo 250 ml",
      "category": "grooming",
      "status": "planned",
      "exclusion": null,
      "selling_price": 321.0,
      "cost": 190.0,
      "mrp": 349.0,
      "daily_units": 14.07,
      "on_hand": 301,
      "lead_days": 9,
      "open_pos": [
        {
          "po_id": "PO-E006-0008",
          "qty": 350,
          "arrives": "2026-10-31"
        }
      ],
      "discount_pct": 0.2492,
      "promo_price": 241.0,
      "uplift": 2.6594,
      "baseline_units": 108.35,
      "promo_units": 288.1513,
      "incremental_units": 179.8013,
      "gmv": 69444.4692,
      "margin_unfunded_pct": 0.2116,
      "margin_at_ask_pct": 0.3112,
      "floor_promo_pct": 0.25,
      "funding_needed_share": 0.1156,
      "funding_ask_share": 0.3,
      "funding_ask_inr": 6915.6318,
      "incremental_margin_inr": 3884.4033,
      "pull_forward_inr": 3533.096,
      "cannibalisation_inr": 0.0,
      "stock_at_start": 496.2143,
      "need_units": 316.9665,
      "stockout_day": null,
      "stock_ok": true,
      "stock_up": null,
      "stock_up_blocked": null,
      "capped_by_stock": false,
      "deep_option": null,
      "banner_rank": 1,
      "banner_candidate": true,
      "cannibalisation": null,
      "verification": {
        "total": 16,
        "verified": 16,
        "rejected": 0
      }
    },
    {
      "sku_code": "GW-03",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "name": "Paw Balm 50 g",
      "category": "grooming",
      "status": "planned",
      "exclusion": null,
      "selling_price": 229.0,
      "cost": 130.0,
      "mrp": 249.0,
      "daily_units": 10.93,
      "on_hand": 340,
      "lead_days": 9,
      "open_pos": [],
      "discount_pct": 0.2489,
      "promo_price": 172.0,
      "uplift": 2.6594,
      "baseline_units": 84.15,
      "promo_units": 223.7927,
      "incremental_units": 139.6427,
      "gmv": 38492.3363,
      "margin_unfunded_pct": 0.2442,
      "margin_at_ask_pct": 0.3436,
      "floor_promo_pct": 0.25,
      "funding_needed_share": 0.0175,
      "funding_ask_share": 0.3,
      "funding_ask_inr": 3826.8544,
      "incremental_margin_inr": 2821.6024,
      "pull_forward_inr": 2073.6934,
      "cannibalisation_inr": 0.0,
      "stock_at_start": 219.7857,
      "need_units": 246.1719,
      "stockout_day": null,
      "stock_ok": true,
      "stock_up": {
        "feasible": true,
        "qty": 30,
        "cost_inr": 3900.0,
        "order_by": "2026-10-26",
        "arrives": "2026-11-04",
        "lead_days": 9
      },
      "stock_up_blocked": null,
      "capped_by_stock": false,
      "deep_option": {
        "depth": 0.2489,
        "promo_price": 172.0,
        "uplift": 2.6594,
        "units": 223.7927,
        "stockout_day": 7,
        "short_units": 26.3862,
        "lost_gmv_inr": 4538.4271,
        "net_inr": 2821.6024
      },
      "banner_rank": 2,
      "banner_candidate": true,
      "cannibalisation": null,
      "verification": {
        "total": 23,
        "verified": 23,
        "rejected": 0
      }
    },
    {
      "sku_code": "PL-01",
      "vendor_id": "E002",
      "brand": "Purrline Foods",
      "name": "Ocean Fish Adult 1.2 kg",
      "category": "cat dry food",
      "status": "planned",
      "exclusion": null,
      "selling_price": 589.0,
      "cost": 450.0,
      "mrp": 640.0,
      "daily_units": 15.93,
      "on_hand": 96,
      "lead_days": 10,
      "open_pos": [
        {
          "po_id": "PO-E002-0012",
          "qty": 500,
          "arrives": "2026-11-02"
        }
      ],
      "discount_pct": 0.2003,
      "promo_price": 471.0,
      "uplift": 2.3348,
      "baseline_units": 122.65,
      "promo_units": 286.3687,
      "incremental_units": 163.7187,
      "gmv": 134879.6745,
      "margin_unfunded_pct": 0.0446,
      "margin_at_ask_pct": 0.1699,
      "floor_promo_pct": 0.14,
      "funding_needed_share": 0.3808,
      "funding_ask_share": 0.5,
      "funding_ask_inr": 16895.7554,
      "incremental_margin_inr": 2447.6132,
      "pull_forward_inr": 3413.5356,
      "cannibalisation_inr": 0.0,
      "stock_at_start": 436.2857,
      "need_units": 315.0056,
      "stockout_day": null,
      "stock_ok": true,
      "stock_up": null,
      "stock_up_blocked": null,
      "capped_by_stock": false,
      "deep_option": null,
      "banner_rank": 4,
      "banner_candidate": false,
      "cannibalisation": {
        "siblings": [
          {
            "sku_code": "PL-02",
            "name": "Chicken & Tuna Adult 1.2 kg",
            "similarity": 0.5,
            "on_promo": true
          }
        ],
        "cost_inr": 0.0,
        "share_pct": 30.0
      },
      "verification": {
        "total": 17,
        "verified": 17,
        "rejected": 0
      }
    },
    {
      "sku_code": "PL-02",
      "vendor_id": "E002",
      "brand": "Purrline Foods",
      "name": "Chicken & Tuna Adult 1.2 kg",
      "category": "cat dry food",
      "status": "planned",
      "exclusion": null,
      "selling_price": 607.0,
      "cost": 465.0,
      "mrp": 660.0,
      "daily_units": 12.86,
      "on_hand": 311,
      "lead_days": 10,
      "open_pos": [],
      "discount_pct": 0.1005,
      "promo_price": 546.0,
      "uplift": 1.4924,
      "baseline_units": 99.0,
      "promo_units": 147.7453,
      "incremental_units": 48.7453,
      "gmv": 80668.9309,
      "margin_unfunded_pct": 0.1484,
      "margin_at_ask_pct": 0.2042,
      "floor_promo_pct": 0.14,
      "funding_needed_share": 0.0,
      "funding_ask_share": 0.5,
      "funding_ask_inr": 4506.2315,
      "incremental_margin_inr": 1377.3256,
      "pull_forward_inr": 1038.2748,
      "cannibalisation_inr": 0.0,
      "stock_at_start": 169.5714,
      "need_units": 162.5198,
      "stockout_day": null,
      "stock_ok": true,
      "stock_up": null,
      "stock_up_blocked": null,
      "capped_by_stock": true,
      "deep_option": {
        "depth": 0.1993,
        "promo_price": 486.0,
        "uplift": 2.3348,
        "units": 231.1497,
        "stockout_day": 5,
        "short_units": 84.6932,
        "lost_gmv_inr": 41160.8897,
        "net_inr": 1965.9091,
        "why": "the vendor's lead time (10 days) cannot land stock before 2026-11-04"
      },
      "banner_rank": 5,
      "banner_candidate": false,
      "cannibalisation": {
        "siblings": [
          {
            "sku_code": "PL-01",
            "name": "Ocean Fish Adult 1.2 kg",
            "similarity": 0.5,
            "on_promo": true
          }
        ],
        "cost_inr": 0.0,
        "share_pct": 30.0
      },
      "verification": {
        "total": 22,
        "verified": 22,
        "rejected": 0
      }
    },
    {
      "sku_code": "BK-04",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Senior Care 3 kg",
      "category": "dog dry food",
      "status": "excluded",
      "exclusion": {
        "code": "outranked",
        "text": "Worth promoting, but the event's SKU limit left it out: better SKUs took the places."
      },
      "selling_price": 1058.0,
      "cost": 840.0,
      "mrp": 1150.0,
      "daily_units": 5.79,
      "on_hand": 121,
      "lead_days": 7,
      "open_pos": [],
      "stock_at_start": 81.0,
      "incremental_margin_inr": null,
      "stock_up": null,
      "stock_up_blocked": null,
      "capped_by_stock": false,
      "deep_option": null,
      "banner_rank": null,
      "banner_candidate": false,
      "cannibalisation": null,
      "verification": {
        "total": 0,
        "verified": 0,
        "rejected": 0
      }
    }
  ],
  "vendors": [
    {
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "skus": [
        "BK-05",
        "BK-01",
        "BK-03"
      ],
      "n_skus": 5,
      "markdown_inr": 89503.3454,
      "ask_inr": 45176.3156,
      "ask_share": 0.5047,
      "gmv": 476197.8309,
      "best_banner_rank": 6,
      "offer": {
        "vendor_id": "E001",
        "share": 0.5,
        "scope": [
          "BK-05",
          "BK-01",
          "BK-03",
          "BK-02",
          "BK-06"
        ],
        "threshold_units": 3400.0,
        "banner_top_n": 3,
        "markdown_inr": 89503.3454,
        "face_inr": 44751.6727,
        "counted_inr": 0.0,
        "banner_cost_inr": 5000.0,
        "probability": 0.0359,
        "decision": "reject_structure",
        "call": "Reject this structure and counter. The chance of 3,400 units in 7 days is 3.6%, so the bonus counts as 0.0 points and the offer is worth 7.5% against 16.4% required. Counter: keep the 3,400 units target but allow 30 days (P = 99.2%); counted value becomes 16.8% against 16.4% required. Guaranteeing the top-3 banner costs us 5,000 of banner value, taken off the funding.",
        "ask_inr": 45176.3156,
        "covers_ask_pct": 0.0,
        "required_pts": 16.3624,
        "offer_key": "festive:E001?share=50&thr=3400&banner=3",
        "counter": {
          "kind": "counter",
          "text": "keep the 3,400 units target but allow 30 days (P = 99.2%); counted value becomes 16.8% against 16.4% required.",
          "counter": {
            "kind": "window",
            "text": "keep the 3,400 units target but allow 30 days (P = 99.2%); counted value becomes 16.8% against 16.4% required.",
            "threshold": 3400.0,
            "window_days": 30.0,
            "scope": [],
            "probability": 0.992,
            "required_base_pts": null,
            "uplift_pts": null,
            "fair_conversion_pts": null,
            "counted_pts_after": 16.8238,
            "meets_requirement": true
          }
        },
        "reply_id": "F001",
        "quote": "We can fund 50% of the markdown on the Barkley range, provided you guarantee a top-3 banner and the range sells 3,400 units between 6th and 12th Nov."
      },
      "assessment": {
        "term_id": "promo-E001",
        "kind": "conditional",
        "term": "margin_pct",
        "label": "9.3977% margin if 3,400 units in 7 days",
        "source": "application",
        "turn": 1,
        "quote": "50% of the markdown if the range sells 3,400 units",
        "decision": "reject_structure",
        "call": "Reject this structure and counter. The chance of 3,400 units in 7 days is 3.6%, so the bonus counts as 0.0 points and the offer is worth 7.5% against 16.4% required. Counter: keep the 3,400 units target but allow 30 days (P = 99.2%); counted value becomes 16.8% against 16.4% required.",
        "reasoning": [
          "Demand over 7 days (ramped new listing, 45.0% forecast uncertainty): P10 1,158 units, P50 1,820 units, P90 2,842 units.",
          "P(3,400 units in 7 days) = 3.6%; under the 60% bar, counts as 0.",
          "No base margin was stated with this bonus, so the 7.5% margin already counted for this vendor is the base.",
          "Counted 7.5 base + 0.0 bonus = 7.5 points against 16.4 required."
        ],
        "base_pts": 7.5008,
        "face_pts": 16.8985,
        "expected_bonus_pts": 0.3374,
        "counted_bonus_pts": 0.0,
        "expected_pts": 7.8382,
        "guaranteed_pts": 7.5008,
        "counted_pts": 7.5008,
        "required_pts": 16.3624,
        "shortfall_pts": -8.8616,
        "probability": 0.0359,
        "tiers": [
          {
            "threshold": 3400.0,
            "bonus_pts": 9.3977,
            "incremental_pts": 9.3977,
            "probability": 0.0359,
            "counted": false
          }
        ],
        "counters": [
          {
            "kind": "threshold",
            "text": "set the target at 1,660 units in 7 days (P = 60.1%); counted value becomes 13.2% against 16.4% required.",
            "threshold": 1660.0,
            "window_days": null,
            "scope": [],
            "probability": 0.6012,
            "required_base_pts": null,
            "uplift_pts": null,
            "fair_conversion_pts": null,
            "counted_pts_after": 13.1507,
            "meets_requirement": false
          },
          {
            "kind": "window",
            "text": "keep the 3,400 units target but allow 30 days (P = 99.2%); counted value becomes 16.8% against 16.4% required.",
            "threshold": 3400.0,
            "window_days": 30.0,
            "scope": [],
            "probability": 0.992,
            "required_base_pts": null,
            "uplift_pts": null,
            "fair_conversion_pts": null,
            "counted_pts_after": 16.8238,
            "meets_requirement": true
          }
        ],
        "recommended_counter": 1,
        "net_pts": null,
        "base_term_id": null,
        "base_assumed": true
      },
      "stated_lead_time_days": null,
      "reading_note": null
    },
    {
      "vendor_id": "E002",
      "brand": "Purrline Foods",
      "skus": [
        "PL-01",
        "PL-04",
        "PL-02"
      ],
      "n_skus": 6,
      "markdown_inr": 91491.7677,
      "ask_inr": 45745.8839,
      "ask_share": 0.5,
      "gmv": 411276.0169,
      "best_banner_rank": 4,
      "offer": {
        "vendor_id": "E002",
        "share": 0.3,
        "scope": [
          "PL-01",
          "PL-04",
          "PL-02",
          "PL-05",
          "PL-03",
          "PL-06"
        ],
        "threshold_units": null,
        "banner_top_n": null,
        "markdown_inr": 91491.7677,
        "face_inr": 27447.5303,
        "counted_inr": 27447.53,
        "banner_cost_inr": 0.0,
        "probability": null,
        "decision": "counter",
        "call": "A flat 30% of the markdown is worth 27,448; we asked for 45,746.",
        "ask_inr": 45745.8839,
        "covers_ask_pct": 0.6,
        "offer_key": "festive:E002?share=30",
        "counter": {
          "kind": "top_up",
          "text": "Ask Purrline Foods to raise the share to 50% of the markdown."
        },
        "reply_id": "F002",
        "quote": "Purrline will fund 30% of the markdown on every Purrline SKU you put on promo."
      },
      "assessment": null,
      "stated_lead_time_days": null,
      "reading_note": null
    },
    {
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "skus": [
        "NP-03"
      ],
      "n_skus": 1,
      "markdown_inr": 12115.9177,
      "ask_inr": 3634.7753,
      "ask_share": 0.3,
      "gmv": 229675.658,
      "best_banner_rank": 23,
      "offer": {
        "vendor_id": "E003",
        "share": 0.35,
        "scope": [
          "NP-03"
        ],
        "threshold_units": 1150.0,
        "banner_top_n": null,
        "markdown_inr": 12115.9177,
        "face_inr": 4240.5712,
        "counted_inr": 3106.59,
        "banner_cost_inr": 0.0,
        "probability": 0.7326,
        "decision": "counter",
        "call": "Accept: counted 25.7% against 23.0% required (P of the first target 73.3%).",
        "ask_inr": 3634.7753,
        "covers_ask_pct": 0.8547,
        "required_pts": 23.0,
        "offer_key": "festive:E003?share=35&thr=1150",
        "counter": {
          "kind": "firm_up",
          "text": "Ask NutriPaws to lower the sales target or make the share unconditional, so that it counts in full."
        },
        "reply_id": "F003",
        "quote": "NutriPaws can support 35% of the discount cost across our range if the range sells 1,150 units during 6-12 Nov."
      },
      "assessment": {
        "term_id": "promo-E003",
        "kind": "conditional",
        "term": "margin_pct",
        "label": "1.8463% margin if 1,150 units in 7 days",
        "source": "application",
        "turn": 1,
        "quote": "35% of the markdown if the range sells 1,150 units",
        "decision": "accept",
        "call": "Accept: counted 25.7% against 23.0% required (P of the first target 73.3%).",
        "reasoning": [
          "Demand over 7 days (ramped new listing, 45.0% forecast uncertainty): P10 923 units, P50 1,418 units, P90 2,177 units.",
          "P(1,150 units in 7 days) = 73.3%; counts.",
          "No base margin was stated with this bonus, so the 24.3% margin already counted for this vendor is the base.",
          "Counted 24.3 base + 1.4 bonus = 25.7 points against 23.0 required."
        ],
        "base_pts": 24.3119,
        "face_pts": 26.1582,
        "expected_bonus_pts": 1.3526,
        "counted_bonus_pts": 1.3526,
        "expected_pts": 25.6645,
        "guaranteed_pts": 24.3119,
        "counted_pts": 25.6645,
        "required_pts": 23.0,
        "shortfall_pts": 2.6645,
        "probability": 0.7326,
        "tiers": [
          {
            "threshold": 1150.0,
            "bonus_pts": 1.8463,
            "incremental_pts": 1.8463,
            "probability": 0.7326,
            "counted": true
          }
        ],
        "counters": [],
        "recommended_counter": null,
        "net_pts": null,
        "base_term_id": null,
        "base_assumed": true
      },
      "stated_lead_time_days": null,
      "reading_note": null
    },
    {
      "vendor_id": "E005",
      "brand": "Litterly",
      "skus": [
        "LT-01",
        "LT-06",
        "LT-02"
      ],
      "n_skus": 3,
      "markdown_inr": 33986.41,
      "ask_inr": 15293.8845,
      "ask_share": 0.45,
      "gmv": 275616.139,
      "best_banner_rank": 15,
      "offer": {
        "decision": "declined",
        "call": "Litterly declined to fund the event.",
        "face_inr": 0.0,
        "counted_inr": 0.0,
        "ask_inr": 15293.8845,
        "covers_ask_pct": 0.0,
        "probability": null,
        "offer_key": null,
        "counter": {
          "kind": "ask",
          "text": "Ask Litterly whether a smaller share is possible."
        }
      },
      "assessment": null,
      "stated_lead_time_days": null,
      "reading_note": "declined"
    }
  ],
  "pos": [
    {
      "po_ref": "PO-PROMO-festive-E006",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "lines": [
        {
          "sku_code": "GW-03",
          "name": "Paw Balm 50 g",
          "qty": 30,
          "cost": 130.0,
          "cost_inr": 3900.0
        }
      ],
      "qty": 30,
      "cost_inr": 3900.0,
      "order_by": "2026-10-26",
      "arrives": "2026-11-04"
    }
  ],
  "headline": "Put 24 SKUs on promo for the Festive Sale, with ₹139,702 of vendor funding asked.",
  "brief": "We promote 24 SKUs. They sell ₹1,706,454 of GMV over the event and add ₹35,820 of margin after the units pulled forward and the sales taken from near-duplicates. Holding the promo margin floor needs ₹139,702 of vendor funding, which lifts the plan's margin to 21.9%.\n\nChicken & Tuna Adult 1.2 kg would run out on day 5 of the event at 19.9% off, the deepest discount that pays. Its vendor cannot land fresh stock in time, so the plan caps it at 10.1%. Paw Balm 50 g can be restocked in time: the plan adds a stock-up PO of 30 units. Stock-up POs for the event cost ₹25,850 in all.\n\nBarkley & Co offers half the markdown on a sales target the range has only a 3.6% chance of reaching, so the offer counts as ₹0; we counter with a longer window. The offer from Purrline Foods counts for ₹27,448, 60.0% of our ask on its SKUs; we ask for a bigger share. The offer from NutriPaws counts for ₹3,107, 85.5% of our ask on its SKUs; we ask for a softer condition. The offer from Tailwind Play counts for ₹4,419, 120.2% of our ask on its SKUs; that covers our ask. Litterly declined to fund the event. The offer from Groomwell counts for ₹3,952, 36.8% of our ask on its SKUs; we ask for a bigger share.",
  "struck": [],
  "readings": [
    {
      "reply_id": "F001",
      "vendor_id": "E001",
      "received_at": "2026-10-23T11:02:00",
      "from": "Anil Rao <orders@barkley.example>",
      "subject": "RE: Festive Sale - funding",
      "body": "Hi team,\n\nThanks for the Festive Sale slot. We can fund 50% of the markdown on the Barkley range, provided you guarantee a top-3 banner and the range sells 3,40",
      "stance": "conditional_offer",
      "summary": "Barkley funds half the markdown if we guarantee a top-3 banner and the range sells a very high target.",
      "lead_time_days": null,
      "terms": [
        {
          "share_pct": 50.0,
          "scope": [],
          "threshold_units": 3400.0,
          "window_days": 7,
          "banner_top_n": 3,
          "quote": "We can fund 50% of the markdown on the Barkley range, provided you guarantee a top-3 banner and the range sells 3,400 units between 6th and 12th Nov.",
          "claims": [
            {
              "id": "promo:F001:t0:share",
              "metric": "promo_ext_share_pct",
              "value": 0.5,
              "status": "verified",
              "reason": null,
              "first_value": null,
              "corrected": false
            },
            {
              "id": "promo:F001:t0:threshold",
              "metric": "promo_ext_threshold_units",
              "value": 3400.0,
              "status": "verified",
              "reason": null,
              "first_value": null,
              "corrected": false
            },
            {
              "id": "promo:F001:t0:banner",
              "metric": "promo_ext_banner_top_n",
              "value": 3.0,
              "status": "verified",
              "reason": null,
              "first_value": null,
              "corrected": false
            }
          ]
        }
      ]
    },
    {
      "reply_id": "F002",
      "vendor_id": "E002",
      "received_at": "2026-10-23T16:40:00",
      "from": "Rakesh Shah <dispatch@purrline.example>",
      "subject": "Festive sale - Purrline support",
      "body": "Dear Sir/Madam,\n\nFor the Festive Sale Purrline will fund 30% of the markdown on every Purrline SKU you put on promo. No other conditions. We will send the credi",
      "stance": "offer",
      "summary": "Purrline funds a flat share of the markdown on every promoted SKU.",
      "lead_time_days": null,
      "terms": [
        {
          "share_pct": 30.0,
          "scope": [],
          "threshold_units": null,
          "window_days": null,
          "banner_top_n": null,
          "quote": "Purrline will fund 30% of the markdown on every Purrline SKU you put on promo.",
          "claims": [
            {
              "id": "promo:F002:t0:share",
              "metric": "promo_ext_share_pct",
              "value": 0.3,
              "status": "verified",
              "reason": null,
              "first_value": null,
              "corrected": false
            }
          ]
        }
      ]
    },
    {
      "reply_id": "F003",
      "vendor_id": "E003",
      "received_at": "2026-10-24T09:15:00",
      "from": "Meera Iyer <supply@nutripaws.example>",
      "subject": "RE: Festive Sale funding ask",
      "body": "Hello,\n\nNutriPaws can support 35% of the discount cost across our range if the range sells 1,150 units during 6-12 Nov. Happy to review after the event.\n\nBest\nM",
      "stance": "conditional_offer",
      "summary": "NutriPaws supports a share of the discount if the range reaches a sales target.",
      "lead_time_days": null,
      "terms": [
        {
          "share_pct": 35.0,
          "scope": [],
          "threshold_units": 1150.0,
          "window_days": 7,
          "banner_top_n": null,
          "quote": "NutriPaws can support 35% of the discount cost across our range if the range sells 1,150 units during 6-12 Nov.",
          "claims": [
            {
              "id": "promo:F003:t0:share",
              "metric": "promo_ext_share_pct",
              "value": 0.35,
              "status": "verified",
              "reason": null,
              "first_value": 0.53,
              "corrected": true
            },
            {
              "id": "promo:F003:t0:threshold",
              "metric": "promo_ext_threshold_units",
              "value": 1150.0,
              "status": "verified",
              "reason": null,
              "first_value": null,
              "corrected": false
            }
          ]
        }
      ]
    },
    {
      "reply_id": "F004",
      "vendor_id": "E005",
      "received_at": "2026-10-24T13:30:00",
      "from": "Sanjay Kulkarni <ops@litterly.example>",
      "subject": "RE: Festive Sale - funding",
      "body": "Hi,\n\nSorry, margins are very thin this quarter and we are not able to fund any discount for the Festive Sale. We will keep stock ready as usual.\n\nSanjay\nLitterl",
      "stance": "decline",
      "summary": "Litterly will not fund any discount this quarter.",
      "lead_time_days": null,
      "terms": []
    }
  ],
  "drafts": [
    {
      "id": "DR-PROMO-festive-E001",
      "kind": "promo_funding",
      "channel": "email",
      "subject": "Festive Sale: funding with Barkley & Co",
      "body": "Hi Anil,\n\nThank you for the offer. On our forecast the range reaching its sales target in the event is only 3.6% likely, so it counts as ₹0 against the ₹45,176 we asked for on those SKUs. Could you give the target a longer window, or turn the bonus into a guaranteed share?\n\nCould you confirm by Friday?\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E001:0",
          "shown": "₹0",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E001:1",
          "shown": "₹45,176",
          "status": "verified",
          "reason": null
        }
      ],
      "claim_ids": [
        "fig:email:E001:0",
        "fig:email:E001:1"
      ],
      "vendor_id": "E001",
      "po_id": null,
      "event_id": "festive",
      "to": "orders@barkley.example",
      "unclaimed_numbers": [],
      "struck": [],
      "status": "pending",
      "decided_at": null,
      "simulated": true,
      "edited": false,
      "note": null,
      "warnings": [],
      "blocked_by": []
    },
    {
      "id": "DR-PROMO-festive-E003",
      "kind": "promo_funding",
      "channel": "email",
      "subject": "Festive Sale: funding with NutriPaws",
      "body": "Hi Meera,\n\nThank you for the offer. It is worth ₹3,107 to us, 85.5% of the ₹3,635 we asked for on those SKUs. Could you lower the sales target or make the share unconditional, so that it counts in full?\n\nCould you confirm by Friday?\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E003:0",
          "shown": "₹3,107",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E003:1",
          "shown": "85.5%",
          "status": "verified",
          "reason": null
        }
      ],
      "claim_ids": [
        "fig:email:E003:0",
        "fig:email:E003:1"
      ],
      "vendor_id": "E003",
      "po_id": null,
      "event_id": "festive",
      "to": "supply@nutripaws.example",
      "unclaimed_numbers": [],
      "struck": [],
      "status": "pending",
      "decided_at": null,
      "simulated": true,
      "edited": false,
      "note": null,
      "warnings": [],
      "blocked_by": []
    }
  ],
  "claims": [
    {
      "id": "promo:F003:t0:share",
      "text": "E003 funds 35% of the markdown",
      "value": 0.35,
      "metric": "promo_ext_share_pct",
      "unit": "pct",
      "sku_key": null,
      "source_ref": {
        "file": "ops/promo_vendor_replies.json",
        "key": "F003",
        "column": "body"
      },
      "origin": "model_extraction",
      "status": "verified",
      "recomputed": 0.35,
      "reason": null,
      "attempts": [
        {
          "attempt": 0,
          "value": 0.53,
          "status": "rejected",
          "reason": "the quote states 35, 1150, 6, 12; the reading says 53",
          "recomputed": 0.35
        },
        {
          "attempt": 1,
          "value": 0.35,
          "status": "verified",
          "reason": null,
          "recomputed": 0.35
        }
      ],
      "evidence": {
        "row": 3,
        "header": "body",
        "raw_value": "NutriPaws can support 35% of the discount cost across our range if the range sells 1,150 units during 6-12 Nov.",
        "normalized_value": 0.35
      }
    },
    {
      "id": "promo:F001:t0:share",
      "text": "E001 funds 50% of the markdown",
      "value": 0.5,
      "metric": "promo_ext_share_pct",
      "unit": "pct",
      "sku_key": null,
      "source_ref": {
        "file": "ops/promo_vendor_replies.json",
        "key": "F001",
        "column": "body"
      },
      "origin": "model_extraction",
      "status": "verified",
      "recomputed": 0.5,
      "reason": null,
      "attempts": [],
      "evidence": {
        "row": 1,
        "header": "body",
        "raw_value": "We can fund 50% of the markdown on the Barkley range, provided you guarantee a top-3 banner and the range sells 3,400 units between 6th and 12th Nov.",
        "normalized_value": 0.5
      }
    },
    {
      "id": "promo:F001:t0:threshold",
      "text": "E001 wants 3400 units sold",
      "value": 3400.0,
      "metric": "promo_ext_threshold_units",
      "unit": "units",
      "sku_key": null,
      "source_ref": {
        "file": "ops/promo_vendor_replies.json",
        "key": "F001",
        "column": "body"
      },
      "origin": "model_extraction",
      "status": "verified",
      "recomputed": 3400.0,
      "reason": null,
      "attempts": [],
      "evidence": {
        "row": 1,
        "header": "body",
        "raw_value": "We can fund 50% of the markdown on the Barkley range, provided you guarantee a top-3 banner and the range sells 3,400 units between 6th and 12th Nov.",
        "normalized_value": 3400.0
      }
    }
  ],
  "verification": {
    "total": 3,
    "verified": 3,
    "rejected": 0,
    "unverifiable": 0
  },
  "corrected": [
    "promo:F003:t0:share"
  ],
  "unresolved": [],
  "assumptions": {
    "elasticity_default": -3.0,
    "max_uplift": 4.0,
    "pull_forward_pct": 15.0,
    "max_discount_pct": 25.0,
    "promo_floor_below_regular_pp": 5.0,
    "safety_buffer_pct": 10.0,
    "baseline_cover_days": 14.0,
    "funding_target_pct": 30.0,
    "funding_max_ask_pct": 60.0,
    "banner_slot_cost_inr": 5000.0,
    "cannibalised_share_pct": 30.0,
    "deal_evaluator": {
      "min_probability": 0.6,
      "value_basis": "risk_adjusted",
      "ramp_by_month": [
        0.5,
        0.75,
        0.9,
        1.0
      ],
      "cv": 0.45,
      "cv_by_category": {},
      "sku_correlation": 0.5,
      "mc_draws": 20000,
      "seed": 42,
      "cost_of_capital_pct_annual": 14.0,
      "inventory_carrying_pct_monthly": 2.0
    }
  },
  "impact_coverage": {
    "module": "promotions_planner",
    "registered": true,
    "status": "shipped",
    "tasks": [
      {
        "task": "promotions",
        "in_scope_pct": 100.0
      }
    ],
    "units": {
      "promotion_event_plan": 1
    },
    "baseline_minutes": {
      "promotion_event_plan": 480.0
    },
    "manual_minutes_replaced": 480.0,
    "baseline_status": "research_estimate"
  },
  "trace": [
    {
      "seq": 1,
      "t_rel_ms": 0.0,
      "type": "stage_started",
      "stage": "ops",
      "model": null,
      "latency_ms": null,
      "cost_usd": null,
      "payload": {
        "task": "promotions",
        "event": "festive",
        "planned_skus": 24
      }
    },
    {
      "seq": 2,
      "t_rel_ms": 0.4,
      "type": "tool_call",
      "stage": "ops",
      "model": null,
      "latency_ms": 0.011,
      "cost_usd": null,
      "payload": {
        "tool": "get_funding_replies",
        "args": {
          "event_id": "festive"
        },
        "result_summary": "file=ops/promo_vendor_replies.json, replies[6]"
      }
    },
    {
      "seq": 3,
      "t_rel_ms": 0.4,
      "type": "model_call",
      "stage": "ops",
      "model": "muse-spark-1.3",
      "latency_ms": 0.297,
      "cost_usd": 0.0,
      "payload": {
        "task": "promo_funding_replies_festive",
        "mode": "mock",
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_steps": 1
      }
    }
  ],
  "decision": {
    "status": "pending"
  }
} as unknown as PromoPlan;

const LIST = {
  "as_of": "2026-10-26",
  "events": [
    {
      "id": "festive",
      "name": "Festive Sale",
      "start": "2026-11-06",
      "end": "2026-11-12",
      "days": 7,
      "traffic_lift_pct": 10.0,
      "banner_slots": 3,
      "days_away": 11,
      "planned_skus": 24,
      "gmv_inr": 1706453.6161,
      "funding_ask_inr": 139702.1196,
      "stock_up_inr": 25850.0,
      "incremental_margin_inr": 35820.4562,
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "payday",
      "name": "Payday Sale",
      "start": "2026-11-28",
      "end": "2026-11-30",
      "days": 3,
      "traffic_lift_pct": 6.0,
      "banner_slots": 2,
      "days_away": 33,
      "planned_skus": 24,
      "gmv_inr": 722023.8119,
      "funding_ask_inr": 63096.4811,
      "stock_up_inr": 0,
      "incremental_margin_inr": 15144.0772,
      "decision": {
        "status": "pending"
      }
    }
  ]
} as unknown as PromoList;

const APPROVED = {
  "event_id": "festive",
  "status": "approved",
  "decided_at": "2026-10-27T04:50:27+00:00",
  "note": null,
  "simulated": true,
  "skus": [
    "BK-01",
    "BK-02",
    "BK-03",
    "BK-05",
    "BK-06"
  ],
  "n_skus": 24,
  "prices": [
    {
      "sku_code": "GW-01",
      "from_price": 321.0,
      "to_price": 241.0
    },
    {
      "sku_code": "GW-03",
      "from_price": 229.0,
      "to_price": 172.0
    },
    {
      "sku_code": "GW-02",
      "from_price": 413.0,
      "to_price": 310.0
    },
    {
      "sku_code": "PL-01",
      "from_price": 589.0,
      "to_price": 471.0
    },
    {
      "sku_code": "BK-05",
      "from_price": 83.0,
      "to_price": 62.0
    }
  ],
  "pos": [
    {
      "po_ref": "PO-PROMO-festive-E001",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "lines": [
        {
          "sku_code": "BK-06",
          "name": "Beef Pate Can 350 g",
          "qty": 110,
          "cost": 135.0,
          "cost_inr": 14850.0
        }
      ],
      "qty": 110,
      "cost_inr": 14850.0,
      "order_by": "2026-10-28",
      "arrives": "2026-11-02",
      "status": "queued_simulated"
    },
    {
      "po_ref": "PO-PROMO-festive-E005",
      "vendor_id": "E005",
      "brand": "Litterly",
      "lines": [
        {
          "sku_code": "LT-06",
          "name": "Litter Scoop Metal",
          "qty": 10,
          "cost": 85.0,
          "cost_inr": 850.0
        }
      ],
      "qty": 10,
      "cost_inr": 850.0,
      "order_by": "2026-10-27",
      "arrives": "2026-11-03",
      "status": "queued_simulated"
    },
    {
      "po_ref": "PO-PROMO-festive-E006",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "lines": [
        {
          "sku_code": "GW-03",
          "name": "Paw Balm 50 g",
          "qty": 30,
          "cost": 130.0,
          "cost_inr": 3900.0
        },
        {
          "sku_code": "GW-02",
          "name": "Deshedding Brush",
          "qty": 10,
          "cost": 250.0,
          "cost_inr": 2500.0
        },
        {
          "sku_code": "GW-06",
          "name": "Tick & Flea Comb",
          "qty": 30,
          "cost": 90.0,
          "cost_inr": 2700.0
        },
        {
          "sku_code": "GW-04",
          "name": "Nail Clipper",
          "qty": 10,
          "cost": 105.0,
          "cost_inr": 1050.0
        }
      ],
      "qty": 80,
      "cost_inr": 10150.0,
      "order_by": "2026-10-26",
      "arrives": "2026-11-04",
      "status": "queued_simulated"
    }
  ],
  "stock_up_inr": 25850.0
} as unknown as PlanDecisionResult;

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export const promoPlan = (over: Partial<PromoPlan> = {}): PromoPlan => ({ ...clone(PLAN), ...over });
export const promoList = (over: Partial<PromoList> = {}): PromoList => ({ ...clone(LIST), ...over });
export const planApproved = (over: Partial<PlanDecisionResult> = {}): PlanDecisionResult => ({ ...clone(APPROVED), ...over });
