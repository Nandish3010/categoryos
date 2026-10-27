import type { PriceWatch, PwDecisionResult } from "@/lib/priceWatch";

/**
 * TRIMMED copies of real mock-mode responses of GET /api/ops/price-watch and the two approve calls. Series are cut to the last
 * 14 days, claims and trace to a handful, SKUs to one per state. All five actions are kept: GW-01 match, BK-01 ask vendor for price
 * protection, LT-01 vendor parity breach (flag breach), NP-04 blip (hold, not matched), TW-02 falling trend (hold).
 */

const WATCH = {
  "as_of": "2026-10-26",
  "window_days": 30,
  "marketplaces": [
    "MarketA",
    "MarketB",
    "MarketC"
  ],
  "mode": "mock",
  "degraded": false,
  "counts": {
    "skus": 36,
    "marketplaces": 3,
    "snapshots": 4320,
    "sustained": 2,
    "blips": 1,
    "trends": 1,
    "breaches": 1,
    "match": 1,
    "ask_vendor_funding": 1,
    "hold": 2,
    "escalate": 0
  },
  "headline": "Match one price, ask one vendor for protection, flag one parity breach; leave the one-day blip and the slow slide alone.",
  "narrative": "Match: Oatmeal Pet Shampoo 250 ml has been 9.0% under our price on MarketB for 6 days. Matching at ₹292 keeps the margin at 34.9%, above the 30.0% floor, and earns ₹2,357 more over the horizon than holding.\n\nAsk the vendor: Chicken & Rice Adult 3 kg has been 6.9% under our price on MarketA for 9 days. Matching would take the margin to 15.5%, under the 20.0% floor, so we ask Barkley & Co for price protection of ₹41 a unit instead of cutting alone.\n\nBreach: Litterly sells Clumping Bentonite Unscented 10 kg at ₹566 on MarketB, 12.0% under our price for 9 days and under the ₹624 minimum advertised price. We do not follow it down; the message asks for parity.\n\nLeave alone: Training Bites 60 g dipped 13.9% under us on MarketC for a single day. A competitor price on Squeaky Plush Duck is falling 0.73 points a day but has not crossed the undercut threshold; we watch it.",
  "struck": [
    "Matching that blip would have cost ₹2,987 of margin for nothing, so we hold and re-check tomorrow."
  ],
  "actions": [
    {
      "sku_code": "BK-01",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Chicken & Rice Adult 3 kg",
      "category": "dog dry food",
      "our_price": 966.0,
      "id": "pw:undercut:BK-01",
      "kind": "undercut",
      "recommendation": "ask_vendor_funding",
      "reasons": [
        "Matching would take the margin under the category floor.",
        "Ask the vendor for price protection that covers the gap, rather than cutting alone."
      ],
      "competitor": {
        "state": "sustained",
        "marketplace": "MarketA",
        "price": 899.0,
        "sustained_marketplaces": 1,
        "match_price": 899.0,
        "cut_pct": 0.0694,
        "margin_now_pct": 0.2133,
        "floor_pct": 0.2,
        "margin_after_match_pct": 0.1546,
        "margin_hold_inr": 69801.89,
        "margin_match_inr": 59720.36,
        "margin_impact_inr": -10081.53,
        "units_hold": 338.8,
        "units_match": 429.6,
        "volume_loss_if_hold_pct": 0.2113,
        "protection_ask_unit_inr": 40.8,
        "protection_ask_inr": 17529.43,
        "elasticity": -5.0,
        "horizon_days": 30
      },
      "claims": [
        {
          "id": "pw:undercut:BK-01:pw_our_price",
          "text": "Chicken & Rice Adult 3 kg: our price",
          "value": 966.0,
          "metric": "pw_our_price",
          "unit": "inr",
          "sku_key": "E001:BK-01",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E001:BK-01",
            "column": "pw_our_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 966.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "pw:undercut:BK-01:pw_competitor_price",
          "text": "Chicken & Rice Adult 3 kg: competitor price on MarketA",
          "value": 899.0,
          "metric": "pw_competitor_price",
          "unit": "inr",
          "sku_key": "E001:BK-01",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E001:BK-01?mp=MarketA",
            "column": "pw_competitor_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 899.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "series": {
        "dates": [
          "2026-10-13",
          "2026-10-14",
          "2026-10-15",
          "2026-10-16",
          "2026-10-17",
          "2026-10-18",
          "2026-10-19",
          "2026-10-20",
          "2026-10-21",
          "2026-10-22",
          "2026-10-23",
          "2026-10-24",
          "2026-10-25",
          "2026-10-26"
        ],
        "our_price": 966.0,
        "competitors": {
          "MarketA": [
            985,
            987,
            981,
            987,
            986,
            899,
            899,
            900,
            898,
            899,
            900,
            899,
            900,
            899
          ],
          "MarketB": [
            990,
            985,
            987,
            992,
            989,
            989,
            990,
            991,
            990,
            986,
            984,
            987,
            986,
            986
          ],
          "MarketC": [
            998,
            998,
            998,
            1002,
            1004,
            1001,
            998,
            1000,
            1005,
            1002,
            1005,
            1004,
            998,
            1003
          ]
        },
        "vendor": {
          "marketplace": "MarketA",
          "prices": [
            972,
            967,
            973,
            971,
            974,
            971,
            966,
            969,
            966,
            975,
            974,
            974,
            969,
            967
          ],
          "dates": [
            "2026-10-13",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
            "2026-10-23",
            "2026-10-24",
            "2026-10-25",
            "2026-10-26"
          ],
          "map_price": 918
        }
      },
      "email_id": "DR-PW-E001",
      "decision": {
        "status": "pending"
      }
    },
    {
      "sku_code": "GW-01",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "name": "Oatmeal Pet Shampoo 250 ml",
      "category": "grooming",
      "our_price": 321.0,
      "id": "pw:undercut:GW-01",
      "kind": "undercut",
      "recommendation": "match",
      "reasons": [
        "Matching keeps the margin at or above the floor and earns more over the horizon than holding."
      ],
      "competitor": {
        "state": "sustained",
        "marketplace": "MarketB",
        "price": 292.0,
        "sustained_marketplaces": 1,
        "match_price": 292.0,
        "cut_pct": 0.0903,
        "margin_now_pct": 0.4081,
        "floor_pct": 0.3,
        "margin_after_match_pct": 0.3493,
        "margin_hold_inr": 40701.36,
        "margin_match_inr": 43058.57,
        "margin_impact_inr": 2357.21,
        "units_hold": 310.7,
        "units_match": 422.1,
        "volume_loss_if_hold_pct": 0.264,
        "protection_ask_unit_inr": 0.0,
        "protection_ask_inr": 0.0,
        "elasticity": -5.0,
        "horizon_days": 30
      },
      "claims": [
        {
          "id": "pw:undercut:GW-01:pw_our_price",
          "text": "Oatmeal Pet Shampoo 250 ml: our price",
          "value": 321.0,
          "metric": "pw_our_price",
          "unit": "inr",
          "sku_key": "E006:GW-01",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E006:GW-01",
            "column": "pw_our_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 321.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "pw:undercut:GW-01:pw_competitor_price",
          "text": "Oatmeal Pet Shampoo 250 ml: competitor price on MarketB",
          "value": 292.0,
          "metric": "pw_competitor_price",
          "unit": "inr",
          "sku_key": "E006:GW-01",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E006:GW-01?mp=MarketB",
            "column": "pw_competitor_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 292.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "series": {
        "dates": [
          "2026-10-13",
          "2026-10-14",
          "2026-10-15",
          "2026-10-16",
          "2026-10-17",
          "2026-10-18",
          "2026-10-19",
          "2026-10-20",
          "2026-10-21",
          "2026-10-22",
          "2026-10-23",
          "2026-10-24",
          "2026-10-25",
          "2026-10-26"
        ],
        "our_price": 321.0,
        "competitors": {
          "MarketA": [
            323,
            323,
            324,
            323,
            323,
            324,
            324,
            323,
            323,
            322,
            324,
            324,
            323,
            324
          ],
          "MarketB": [
            324,
            325,
            324,
            324,
            325,
            324,
            323,
            323,
            292,
            292,
            292,
            292,
            292,
            292
          ],
          "MarketC": [
            328,
            328,
            327,
            327,
            329,
            328,
            329,
            327,
            328,
            329,
            329,
            328,
            327,
            329
          ]
        },
        "vendor": {
          "marketplace": "MarketC",
          "prices": [
            324,
            322,
            322,
            324,
            324,
            324,
            324,
            324,
            322,
            323,
            322,
            321,
            321,
            323
          ],
          "dates": [
            "2026-10-13",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
            "2026-10-23",
            "2026-10-24",
            "2026-10-25",
            "2026-10-26"
          ],
          "map_price": null
        }
      },
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    },
    {
      "sku_code": "LT-01",
      "vendor_id": "E005",
      "brand": "Litterly",
      "name": "Clumping Bentonite Unscented 10 kg",
      "category": "cat litter",
      "our_price": 643.0,
      "id": "pw:breach:LT-01",
      "kind": "breach",
      "recommendation": "flag_breach",
      "reasons": [
        "The vendor sells on MarketB 12.0% under our price for 9 days (tolerance 3%).",
        "The vendor's price is under the minimum advertised price of ₹624 for 9 days.",
        "Do not cut our price to follow the vendor; ask the vendor to restore parity."
      ],
      "vendor": {
        "marketplace": "MarketB",
        "price": 566.0,
        "gap_below_pct": 0.1198,
        "parity_days": 9,
        "map_price": 624,
        "map_days": 9,
        "parity_breach": true,
        "map_breach": true,
        "breach": true,
        "lost_units": 253.9,
        "lost_margin_inr": 41388.04,
        "price_premium_pct": 0.136,
        "dates": [
          "2026-10-13",
          "2026-10-14",
          "2026-10-15",
          "2026-10-16",
          "2026-10-17",
          "2026-10-18",
          "2026-10-19",
          "2026-10-20",
          "2026-10-21",
          "2026-10-22",
          "2026-10-23",
          "2026-10-24",
          "2026-10-25",
          "2026-10-26"
        ],
        "prices": [
          647,
          648,
          648,
          646,
          646,
          566,
          566,
          566,
          566,
          566,
          566,
          566,
          566,
          566
        ]
      },
      "claims": [
        {
          "id": "pw:breach:LT-01:pw_our_price",
          "text": "Clumping Bentonite Unscented 10 kg: our price",
          "value": 643.0,
          "metric": "pw_our_price",
          "unit": "inr",
          "sku_key": "E005:LT-01",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E005:LT-01",
            "column": "pw_our_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 643.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "pw:breach:LT-01:pw_vendor_price",
          "text": "Clumping Bentonite Unscented 10 kg: vendor price on MarketB",
          "value": 566.0,
          "metric": "pw_vendor_price",
          "unit": "inr",
          "sku_key": "E005:LT-01",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E005:LT-01?mp=MarketB",
            "column": "pw_vendor_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 566.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "series": {
        "dates": [
          "2026-10-13",
          "2026-10-14",
          "2026-10-15",
          "2026-10-16",
          "2026-10-17",
          "2026-10-18",
          "2026-10-19",
          "2026-10-20",
          "2026-10-21",
          "2026-10-22",
          "2026-10-23",
          "2026-10-24",
          "2026-10-25",
          "2026-10-26"
        ],
        "our_price": 643.0,
        "competitors": {
          "MarketA": [
            657,
            661,
            656,
            660,
            659,
            661,
            658,
            657,
            657,
            656,
            657,
            657,
            656,
            658
          ],
          "MarketB": [
            657,
            657,
            658,
            660,
            659,
            661,
            657,
            659,
            659,
            659,
            656,
            661,
            657,
            661
          ],
          "MarketC": [
            638,
            638,
            636,
            635,
            636,
            636,
            635,
            639,
            636,
            637,
            637,
            638,
            635,
            638
          ]
        },
        "vendor": {
          "marketplace": "MarketB",
          "prices": [
            647,
            648,
            648,
            646,
            646,
            566,
            566,
            566,
            566,
            566,
            566,
            566,
            566,
            566
          ],
          "dates": [
            "2026-10-13",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
            "2026-10-23",
            "2026-10-24",
            "2026-10-25",
            "2026-10-26"
          ],
          "map_price": 624
        }
      },
      "email_id": "DR-PW-E005",
      "decision": {
        "status": "pending"
      }
    },
    {
      "sku_code": "TW-02",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Squeaky Plush Duck",
      "category": "toys",
      "our_price": 275.0,
      "id": "pw:trend:TW-02",
      "kind": "trend",
      "recommendation": "hold",
      "reasons": [
        "The competitor price on MarketC is falling 0.7% a day but has not crossed the 3% undercut threshold. Watch it."
      ],
      "competitor": {
        "state": "trend",
        "marketplace": "MarketC",
        "price": 268.0,
        "sustained_marketplaces": 0,
        "slope_pct_per_day": -0.0073
      },
      "claims": [
        {
          "id": "pw:trend:TW-02:pw_our_price",
          "text": "Squeaky Plush Duck: our price",
          "value": 275.0,
          "metric": "pw_our_price",
          "unit": "inr",
          "sku_key": "E004:TW-02",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E004:TW-02",
            "column": "pw_our_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 275.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "pw:trend:TW-02:pw_competitor_price",
          "text": "Squeaky Plush Duck: competitor price on MarketC",
          "value": 268.0,
          "metric": "pw_competitor_price",
          "unit": "inr",
          "sku_key": "E004:TW-02",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E004:TW-02?mp=MarketC",
            "column": "pw_competitor_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 268.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "series": {
        "dates": [
          "2026-10-13",
          "2026-10-14",
          "2026-10-15",
          "2026-10-16",
          "2026-10-17",
          "2026-10-18",
          "2026-10-19",
          "2026-10-20",
          "2026-10-21",
          "2026-10-22",
          "2026-10-23",
          "2026-10-24",
          "2026-10-25",
          "2026-10-26"
        ],
        "our_price": 275.0,
        "competitors": {
          "MarketA": [
            271,
            273,
            271,
            271,
            271,
            272,
            273,
            271,
            272,
            271,
            272,
            272,
            271,
            272
          ],
          "MarketB": [
            273,
            273,
            273,
            273,
            274,
            273,
            274,
            274,
            273,
            273,
            272,
            272,
            272,
            273
          ],
          "MarketC": [
            273,
            272,
            272,
            274,
            274,
            273,
            273,
            280,
            278,
            276,
            274,
            272,
            270,
            268
          ]
        },
        "vendor": {
          "marketplace": "MarketB",
          "prices": [
            277,
            278,
            275,
            277,
            277,
            276,
            278,
            276,
            276,
            277,
            276,
            278,
            277,
            276
          ],
          "dates": [
            "2026-10-13",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
            "2026-10-23",
            "2026-10-24",
            "2026-10-25",
            "2026-10-26"
          ],
          "map_price": null
        }
      },
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    },
    {
      "sku_code": "NP-04",
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "name": "Training Bites 60 g",
      "category": "treats",
      "our_price": 101.0,
      "id": "pw:blip:NP-04",
      "kind": "blip",
      "recommendation": "hold",
      "reasons": [
        "The undercut on MarketC has lasted 1 day, under the 3 days that make it sustained. Do not match; re-check tomorrow.",
        "Matching a one-day dip would give margin away for nothing."
      ],
      "competitor": {
        "state": "blip",
        "marketplace": "MarketC",
        "price": 87.0,
        "sustained_marketplaces": 0,
        "match_price": 87.0,
        "cut_pct": 0.1386,
        "margin_now_pct": 0.3069,
        "floor_pct": 0.28,
        "margin_after_match_pct": 0.1954,
        "margin_hold_inr": 22585.39,
        "margin_match_inr": 19598.57,
        "margin_impact_inr": -2986.82,
        "units_hold": 728.6,
        "units_match": 1152.9,
        "volume_loss_if_hold_pct": 0.368,
        "protection_ask_unit_inr": 7.36,
        "protection_ask_inr": 8485.03,
        "elasticity": -5.0,
        "horizon_days": 30
      },
      "claims": [
        {
          "id": "pw:blip:NP-04:pw_our_price",
          "text": "Training Bites 60 g: our price",
          "value": 101.0,
          "metric": "pw_our_price",
          "unit": "inr",
          "sku_key": "E003:NP-04",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E003:NP-04",
            "column": "pw_our_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 101.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "pw:blip:NP-04:pw_competitor_price",
          "text": "Training Bites 60 g: competitor price on MarketC",
          "value": 87.0,
          "metric": "pw_competitor_price",
          "unit": "inr",
          "sku_key": "E003:NP-04",
          "source_ref": {
            "file": "ops/price_snapshots.csv",
            "key": "E003:NP-04?mp=MarketC",
            "column": "pw_competitor_price"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 87.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "series": {
        "dates": [
          "2026-10-13",
          "2026-10-14",
          "2026-10-15",
          "2026-10-16",
          "2026-10-17",
          "2026-10-18",
          "2026-10-19",
          "2026-10-20",
          "2026-10-21",
          "2026-10-22",
          "2026-10-23",
          "2026-10-24",
          "2026-10-25",
          "2026-10-26"
        ],
        "our_price": 101.0,
        "competitors": {
          "MarketA": [
            104,
            104,
            104,
            103,
            104,
            104,
            103,
            103,
            104,
            104,
            104,
            104,
            104,
            104
          ],
          "MarketB": [
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100
          ],
          "MarketC": [
            100,
            100,
            101,
            101,
            100,
            101,
            100,
            100,
            101,
            101,
            101,
            101,
            100,
            87
          ]
        },
        "vendor": {
          "marketplace": "MarketA",
          "prices": [
            101,
            102,
            102,
            102,
            102,
            101,
            101,
            101,
            102,
            102,
            101,
            102,
            101,
            102
          ],
          "dates": [
            "2026-10-13",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
            "2026-10-23",
            "2026-10-24",
            "2026-10-25",
            "2026-10-26"
          ],
          "map_price": null
        }
      },
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    }
  ],
  "skus": [
    {
      "sku_code": "BK-01",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Chicken & Rice Adult 3 kg",
      "our_price": 966.0,
      "lowest_competitor": 899.0,
      "lowest_marketplace": "MarketA",
      "gap_pct": -0.0694,
      "state": "sustained",
      "vendor_breach": false
    },
    {
      "sku_code": "BK-02",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Lamb & Rice Adult 3 kg",
      "our_price": 1012.0,
      "lowest_competitor": 1016.0,
      "lowest_marketplace": "MarketC",
      "gap_pct": 0.004,
      "state": "ok",
      "vendor_breach": false
    },
    {
      "sku_code": "BK-03",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Puppy Starter 1 kg",
      "our_price": 386.0,
      "lowest_competitor": 392.0,
      "lowest_marketplace": "MarketC",
      "gap_pct": 0.0155,
      "state": "ok",
      "vendor_breach": false
    },
    {
      "sku_code": "NP-04",
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "name": "Training Bites 60 g",
      "our_price": 101.0,
      "lowest_competitor": 87.0,
      "lowest_marketplace": "MarketC",
      "gap_pct": -0.1386,
      "state": "blip",
      "vendor_breach": false
    },
    {
      "sku_code": "TW-02",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Squeaky Plush Duck",
      "our_price": 275.0,
      "lowest_competitor": 268.0,
      "lowest_marketplace": "MarketC",
      "gap_pct": -0.0255,
      "state": "trend",
      "vendor_breach": false
    },
    {
      "sku_code": "LT-01",
      "vendor_id": "E005",
      "brand": "Litterly",
      "name": "Clumping Bentonite Unscented 10 kg",
      "our_price": 643.0,
      "lowest_competitor": 638.0,
      "lowest_marketplace": "MarketC",
      "gap_pct": -0.0078,
      "state": "ok",
      "vendor_breach": true
    },
    {
      "sku_code": "GW-01",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "name": "Oatmeal Pet Shampoo 250 ml",
      "our_price": 321.0,
      "lowest_competitor": 292.0,
      "lowest_marketplace": "MarketB",
      "gap_pct": -0.0903,
      "state": "sustained",
      "vendor_breach": false
    }
  ],
  "drafts": [
    {
      "id": "DR-PW-E001",
      "kind": "price_watch",
      "channel": "email",
      "subject": "Price protection request: Chicken & Rice Adult 3 kg",
      "body": "Hi Anil,\n\nA competitor on MarketA has been 6.9% under our price on Chicken & Rice Adult 3 kg for 9 days. Matching would take our margin to 15.5%, under the 20.0% floor. Could you share price protection of ₹41 a unit for the next period?\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E001:0",
          "shown": "6.9%",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E001:1",
          "shown": "9",
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
      "id": "DR-PW-E005",
      "kind": "price_watch",
      "channel": "email",
      "subject": "Price parity on Clumping Bentonite Unscented 10 kg",
      "body": "Hi Sanjay,\n\nOn MarketB, Clumping Bentonite Unscented 10 kg is listed at ₹566 on your own storefront, 12.0% under our price, for 9 days. That breaks price parity and sits under the ₹624 minimum advertised price. Please restore parity by Friday; we will not follow the lower price down.\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E005:0",
          "shown": "₹566",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E005:1",
          "shown": "12.0%",
          "status": "verified",
          "reason": null
        }
      ],
      "claim_ids": [
        "fig:email:E005:0",
        "fig:email:E005:1"
      ],
      "vendor_id": "E005",
      "po_id": null,
      "to": "ops@litterly.example",
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
      "id": "fig:brief:0",
      "text": "Oatmeal Pet Shampoo 250 ml: competitor under our price on MarketB",
      "value": 0.0903,
      "metric": "pw_below_pct",
      "unit": "pct",
      "sku_key": "E006:GW-01",
      "source_ref": {
        "file": "ops/price_snapshots.csv",
        "key": "E006:GW-01?mp=MarketB",
        "column": "pw_below_pct"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 0.0903,
      "reason": null,
      "attempts": [],
      "evidence": null
    },
    {
      "id": "fig:brief:1",
      "text": "Oatmeal Pet Shampoo 250 ml: days under us in a row on MarketB",
      "value": 6.0,
      "metric": "pw_streak_days",
      "unit": "units",
      "sku_key": "E006:GW-01",
      "source_ref": {
        "file": "ops/price_snapshots.csv",
        "key": "E006:GW-01?mp=MarketB",
        "column": "pw_streak_days"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 6.0,
      "reason": null,
      "attempts": [],
      "evidence": null
    },
    {
      "id": "fig:brief:2",
      "text": "Oatmeal Pet Shampoo 250 ml: match price",
      "value": 292.0,
      "metric": "pw_match_price",
      "unit": "inr",
      "sku_key": "E006:GW-01",
      "source_ref": {
        "file": "ops/price_snapshots.csv",
        "key": "E006:GW-01",
        "column": "pw_match_price"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 292.0,
      "reason": null,
      "attempts": [],
      "evidence": null
    }
  ],
  "verification": {
    "total": 3,
    "verified": 3,
    "rejected": 0,
    "unverifiable": 0
  },
  "thresholds": {
    "undercut_threshold_pct": 3.0,
    "min_sustained_days": 3,
    "parity_tolerance_pct": 3.0,
    "parity_min_days": 3,
    "max_cut_pct": 12.0,
    "horizon_days": 30,
    "comparison_share_pct": 70.0
  },
  "impact_coverage": {
    "module": "competitor_monitor",
    "registered": true,
    "status": "shipped",
    "tasks": [
      {
        "task": "competitor_monitoring",
        "in_scope_pct": 100.0
      }
    ],
    "units": {
      "competitor_price_sweep": 1
    },
    "baseline_minutes": {
      "competitor_price_sweep": 30.0
    },
    "manual_minutes_replaced": 30.0,
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
        "task": "price_watch",
        "as_of": "2026-10-26",
        "snapshots": 4320
      }
    },
    {
      "seq": 2,
      "t_rel_ms": 15.7,
      "type": "tool_call",
      "stage": "ops",
      "model": null,
      "latency_ms": 15.383,
      "cost_usd": null,
      "payload": {
        "tool": "get_price_watch_summary",
        "args": {},
        "result_summary": "as_of=2026-10-26, window_days=30, marketplaces[3], counts{11}, actions[5]"
      }
    },
    {
      "seq": 3,
      "t_rel_ms": 15.9,
      "type": "model_call",
      "stage": "ops",
      "model": "muse-spark-1.3",
      "latency_ms": 15.821,
      "cost_usd": 0.0,
      "payload": {
        "task": "pw_brief",
        "mode": "mock",
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_steps": 1
      }
    }
  ],
  "decisions": []
} as unknown as PriceWatch;

const MATCH = {
  "action_id": "pw:undercut:GW-01",
  "status": "approved",
  "decided_at": "2026-10-27T04:50:27+00:00",
  "note": null,
  "simulated": true,
  "effect": {
    "type": "price_change",
    "sku_code": "GW-01",
    "from_price": 321.0,
    "to_price": 292.0,
    "reason": "match MarketB"
  },
  "recommendation": "match"
} as unknown as PwDecisionResult;

const BREACH = {
  "action_id": "pw:breach:LT-01",
  "status": "approved",
  "decided_at": "2026-10-27T04:50:27+00:00",
  "note": null,
  "simulated": true,
  "effect": {
    "type": "vendor_message",
    "draft_id": "DR-PW-E005",
    "vendor_id": "E005",
    "draft_status": "sent_simulated"
  },
  "recommendation": "flag_breach"
} as unknown as PwDecisionResult;

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export const priceWatch = (over: Partial<PriceWatch> = {}): PriceWatch => ({ ...clone(WATCH), ...over });
export const matchApproved = (over: Partial<PwDecisionResult> = {}): PwDecisionResult => ({ ...clone(MATCH), ...over });
export const breachApproved = (over: Partial<PwDecisionResult> = {}): PwDecisionResult => ({ ...clone(BREACH), ...over });
