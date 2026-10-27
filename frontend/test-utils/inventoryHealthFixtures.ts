import type { InventoryHealth, IhDecisionResult } from "@/lib/inventoryHealth";

/**
 * TRIMMED copy of a real mock-mode response of GET /api/ops/inventory-health and its approve calls. Claims are cut to a handful per
 * action, the trace to six rows and the SKU table to the SKUs with actions plus three healthy ones. All ten actions are kept.
 */

const REVIEW = {
  "as_of": "2026-10-26",
  "mode": "mock",
  "degraded": false,
  "counts": {
    "skus": 38,
    "live_skus": 36,
    "legacy_lots": 2,
    "actions": 10,
    "stock_out": 4,
    "overbuy": 1,
    "dead": 2,
    "aged": 3,
    "excess": 0,
    "reorder": 2,
    "expedite_po": 2,
    "pause_po": 1,
    "return_to_vendor": 2,
    "liquidate": 3,
    "stock_value_inr": 3335747.0,
    "stuck_value_inr": 210740.0
  },
  "headline": "Reorder two SKUs, chase two late POs, pause one overbuy, and clear the stuck stock by return or promo.",
  "narrative": "Order now: Peanut Butter Biscuits 400 g runs out in 0.38 days. Order 1,800 units (₹594,000 at cost) so the stock lasts until the next review. Clumping Bentonite 5 kg runs out in 4.98 days and its PO is late, which means about 2.02 days out of stock unless Litterly ships it now.\n\nOverstock: Collapsible Travel Bowl already has 30.03 days of cover without its open PO. Pause the 300 units on it. Training Bites (old pack): return 240 units for ₹15,048 of credit while the window has 66 days left. Oatmeal Shampoo (old label) has no return route; clear it on a promo at ₹113 a unit to recover ₹20,340.",
  "struck": [],
  "actions": [
    {
      "id": "ih:stock_out:NP-03",
      "sku_code": "NP-03",
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "name": "Peanut Butter Biscuits 400 g",
      "category": "treats",
      "legacy": false,
      "kind": "stock_out",
      "recommendation": "reorder",
      "severity": "critical",
      "reasons": [
        "Stock ends in 0.4 days but the next PO lands in 7.0 days: about 6.6 days out of stock, 380 units not sold. Its PO is past its promised date.",
        "Cover including inbound is 17.4 days, under the 18.0 days that lead time (6), the review cycle and safety stock need. Order 1800 units now to reach 30 days of cover when it lands."
      ],
      "reorder": {
        "qty": 1800,
        "needed_units": 1447,
        "moq_units": 600,
        "lead_time_days": 6,
        "order_by": "2026-10-26",
        "cost_inr": 594000.0,
        "overbuy_units": 353,
        "moq_driven": false
      },
      "claims": [
        {
          "id": "ih:stock_out:NP-03:ih_on_hand_units",
          "text": "Peanut Butter Biscuits 400 g: units on hand",
          "value": 22.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E003:NP-03",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003:NP-03",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 22.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:NP-03:ih_stock_value_inr",
          "text": "Peanut Butter Biscuits 400 g: stock at cost",
          "value": 7260.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E003:NP-03",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003:NP-03",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 7260.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:NP-03:ih_daily_demand",
          "text": "Peanut Butter Biscuits 400 g: forecast units a day",
          "value": 57.46,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E003:NP-03",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E003:NP-03",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 57.46,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:NP-03:ih_cover_days",
          "text": "Peanut Butter Biscuits 400 g: days of cover on hand",
          "value": 0.38,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E003:NP-03",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E003:NP-03",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 0.38,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:NP-03:ih_lead_time_days",
          "text": "Peanut Butter Biscuits 400 g: vendor lead time",
          "value": 6.0,
          "metric": "ih_lead_time_days",
          "unit": "units",
          "sku_key": "E003:NP-03",
          "source_ref": {
            "file": "ops/vendors.json",
            "key": "E003:NP-03",
            "column": "ih_lead_time_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 6.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 22,
        "daily_demand": 57.46,
        "cover_days": 0.38,
        "inbound_units": 600,
        "cover_inbound_days": 17.44,
        "run_out_day": 0.38,
        "short_days": 6.62,
        "lead_time_days": 6,
        "moq_units": 600,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [
          {
            "po_id": "PO-E003-0010",
            "qty": 600,
            "promised": "2026-10-20",
            "arrives_in_days": 7.0,
            "overdue": true,
            "received": 300,
            "ordered": 900
          }
        ],
        "stock_value_inr": 7260.0,
        "days_since_sale": 1,
        "oldest_age_days": 50,
        "aged_units": 0,
        "terms": {
          "return_terms": "sell_or_return",
          "return_window_ends": "2026-12-25",
          "restocking_fee_pct": 5.0
        },
        "legacy": false,
        "band_state": "below"
      },
      "note": "Stock ends in 0.38 days, inside the vendor's lead time. Raise the order for 1,800 units today.",
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:stock_out:LT-05",
      "sku_code": "LT-05",
      "vendor_id": "E005",
      "brand": "Litterly",
      "name": "Clumping Bentonite 5 kg",
      "category": "cat litter",
      "legacy": false,
      "kind": "stock_out",
      "recommendation": "expedite_po",
      "severity": "high",
      "reasons": [
        "Stock ends in 5.0 days but the next PO lands in 7.0 days: about 2.0 days out of stock, 57 units not sold. Its PO is past its promised date.",
        "Cover after the PO lands is healthy, so the fix is to get the PO in sooner, not to order more."
      ],
      "reorder": null,
      "claims": [
        {
          "id": "ih:stock_out:LT-05:ih_on_hand_units",
          "text": "Clumping Bentonite 5 kg: units on hand",
          "value": 142.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E005:LT-05",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E005:LT-05",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 142.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-05:ih_stock_value_inr",
          "text": "Clumping Bentonite 5 kg: stock at cost",
          "value": 39050.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E005:LT-05",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E005:LT-05",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 39050.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-05:ih_daily_demand",
          "text": "Clumping Bentonite 5 kg: forecast units a day",
          "value": 28.5,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E005:LT-05",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E005:LT-05",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 28.5,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-05:ih_cover_days",
          "text": "Clumping Bentonite 5 kg: days of cover on hand",
          "value": 4.98,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E005:LT-05",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E005:LT-05",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 4.98,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-05:ih_lead_time_days",
          "text": "Clumping Bentonite 5 kg: vendor lead time",
          "value": 8.0,
          "metric": "ih_lead_time_days",
          "unit": "units",
          "sku_key": "E005:LT-05",
          "source_ref": {
            "file": "ops/vendors.json",
            "key": "E005:LT-05",
            "column": "ih_lead_time_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 8.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 142,
        "daily_demand": 28.5,
        "cover_days": 4.98,
        "inbound_units": 700,
        "cover_inbound_days": 31.56,
        "run_out_day": 4.98,
        "short_days": 2.02,
        "lead_time_days": 8,
        "moq_units": 400,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [
          {
            "po_id": "PO-E005-0008",
            "qty": 700,
            "promised": "2026-10-19",
            "arrives_in_days": 7.0,
            "overdue": true,
            "received": 0,
            "ordered": 700
          }
        ],
        "stock_value_inr": 39050.0,
        "days_since_sale": 1,
        "oldest_age_days": 39,
        "aged_units": 0,
        "terms": {
          "return_terms": "none",
          "return_window_ends": null,
          "restocking_fee_pct": 0.0
        },
        "legacy": false,
        "band_state": "below"
      },
      "note": "The PO is past its promised date and the stock ends in 4.98 days. Chase the vendor to ship now rather than ordering more.",
      "email_id": "DR-IH-E005",
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:stock_out:PL-01",
      "sku_code": "PL-01",
      "vendor_id": "E002",
      "brand": "Purrline Foods",
      "name": "Ocean Fish Adult 1.2 kg",
      "category": "cat dry food",
      "legacy": false,
      "kind": "stock_out",
      "recommendation": "expedite_po",
      "severity": "high",
      "reasons": [
        "Stock ends in 6.0 days but the next PO lands in 7.0 days: about 1.0 days out of stock, 16 units not sold. Its PO is past its promised date.",
        "Cover after the PO lands is healthy, so the fix is to get the PO in sooner, not to order more."
      ],
      "reorder": null,
      "claims": [
        {
          "id": "ih:stock_out:PL-01:ih_on_hand_units",
          "text": "Ocean Fish Adult 1.2 kg: units on hand",
          "value": 96.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E002:PL-01",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E002:PL-01",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 96.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:PL-01:ih_stock_value_inr",
          "text": "Ocean Fish Adult 1.2 kg: stock at cost",
          "value": 43200.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E002:PL-01",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E002:PL-01",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 43200.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:PL-01:ih_daily_demand",
          "text": "Ocean Fish Adult 1.2 kg: forecast units a day",
          "value": 15.93,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E002:PL-01",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E002:PL-01",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 15.93,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:PL-01:ih_cover_days",
          "text": "Ocean Fish Adult 1.2 kg: days of cover on hand",
          "value": 6.03,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E002:PL-01",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E002:PL-01",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 6.03,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:PL-01:ih_lead_time_days",
          "text": "Ocean Fish Adult 1.2 kg: vendor lead time",
          "value": 10.0,
          "metric": "ih_lead_time_days",
          "unit": "units",
          "sku_key": "E002:PL-01",
          "source_ref": {
            "file": "ops/vendors.json",
            "key": "E002:PL-01",
            "column": "ih_lead_time_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 10.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 96,
        "daily_demand": 15.93,
        "cover_days": 6.03,
        "inbound_units": 500,
        "cover_inbound_days": 38.39,
        "run_out_day": 6.03,
        "short_days": 0.97,
        "lead_time_days": 10,
        "moq_units": 300,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [
          {
            "po_id": "PO-E002-0012",
            "qty": 500,
            "promised": "2026-10-24",
            "arrives_in_days": 7.0,
            "overdue": true,
            "received": 0,
            "ordered": 500
          }
        ],
        "stock_value_inr": 43200.0,
        "days_since_sale": 1,
        "oldest_age_days": 50,
        "aged_units": 0,
        "terms": {
          "return_terms": "none",
          "return_window_ends": null,
          "restocking_fee_pct": 0.0
        },
        "legacy": false,
        "band_state": "below"
      },
      "note": null,
      "email_id": "DR-IH-E002",
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:dead:GW-91",
      "sku_code": "GW-91",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "name": "Oatmeal Shampoo (old label)",
      "category": "",
      "legacy": true,
      "kind": "dead",
      "recommendation": "liquidate",
      "severity": "high",
      "reasons": [
        "No sale for 100 days with 180 units on hand (₹21,240 at cost).",
        "No sell-or-return terms on file for this SKU: clear it with a promo."
      ],
      "clear": {
        "kind": "dead",
        "units": 180,
        "excess_units": 0,
        "aged_units": 180,
        "value_inr": 21240.0,
        "liquidate": {
          "units": 180,
          "discount_pct": 0.4,
          "price_inr": 113.0,
          "recovery_inr": 20340.0,
          "write_down_inr": 900.0,
          "clear_days": null,
          "floor_applied": false
        },
        "rtv": null
      },
      "claims": [
        {
          "id": "ih:dead:GW-91:ih_on_hand_units",
          "text": "Oatmeal Shampoo (old label): units on hand",
          "value": 180.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E006:GW-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E006:GW-91",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 180.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:GW-91:ih_stock_value_inr",
          "text": "Oatmeal Shampoo (old label): stock at cost",
          "value": 21240.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E006:GW-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E006:GW-91",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 21240.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:GW-91:ih_clear_units",
          "text": "Oatmeal Shampoo (old label): units to clear",
          "value": 180.0,
          "metric": "ih_clear_units",
          "unit": "units",
          "sku_key": "E006:GW-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E006:GW-91",
            "column": "ih_clear_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 180.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:GW-91:ih_clear_value_inr",
          "text": "Oatmeal Shampoo (old label): cost of the units to clear",
          "value": 21240.0,
          "metric": "ih_clear_value_inr",
          "unit": "inr",
          "sku_key": "E006:GW-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E006:GW-91",
            "column": "ih_clear_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 21240.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:GW-91:ih_days_since_sale",
          "text": "Oatmeal Shampoo (old label): days since the last sale",
          "value": 100.0,
          "metric": "ih_days_since_sale",
          "unit": "units",
          "sku_key": "E006:GW-91",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E006:GW-91",
            "column": "ih_days_since_sale"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 100.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 180,
        "daily_demand": 0.0,
        "cover_days": null,
        "inbound_units": 0,
        "cover_inbound_days": null,
        "run_out_day": null,
        "short_days": 0.0,
        "lead_time_days": 9,
        "moq_units": 100,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [],
        "stock_value_inr": 21240.0,
        "days_since_sale": 100,
        "oldest_age_days": 189,
        "aged_units": 180,
        "terms": {
          "return_terms": "none",
          "return_window_ends": null,
          "restocking_fee_pct": 0.0
        },
        "legacy": true,
        "band_state": "not_moving"
      },
      "note": "No return route: promote at ₹113 a unit to recover ₹20,340.",
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:dead:NP-91",
      "sku_code": "NP-91",
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "name": "Training Bites (old pack)",
      "category": "",
      "legacy": true,
      "kind": "dead",
      "recommendation": "return_to_vendor",
      "severity": "high",
      "reasons": [
        "No sale for 116 days with 240 units on hand (₹15,840 at cost).",
        "Sell-or-return terms are open until 2026-12-31 (66 days): return the stock for ₹15,048 of credit, more than a promo would recover (₹14,880)."
      ],
      "clear": {
        "kind": "dead",
        "units": 240,
        "excess_units": 0,
        "aged_units": 240,
        "value_inr": 15840.0,
        "liquidate": {
          "units": 240,
          "discount_pct": 0.4,
          "price_inr": 62.0,
          "recovery_inr": 14880.0,
          "write_down_inr": 960.0,
          "clear_days": null,
          "floor_applied": false
        },
        "rtv": {
          "units": 240,
          "credit_inr": 15048.0,
          "days_left": 66,
          "window_ends": "2026-12-31",
          "open": true,
          "urgent": false,
          "restocking_fee_pct": 5.0
        }
      },
      "claims": [
        {
          "id": "ih:dead:NP-91:ih_on_hand_units",
          "text": "Training Bites (old pack): units on hand",
          "value": 240.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E003:NP-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003:NP-91",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 240.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:NP-91:ih_stock_value_inr",
          "text": "Training Bites (old pack): stock at cost",
          "value": 15840.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E003:NP-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003:NP-91",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 15840.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:NP-91:ih_clear_units",
          "text": "Training Bites (old pack): units to clear",
          "value": 240.0,
          "metric": "ih_clear_units",
          "unit": "units",
          "sku_key": "E003:NP-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003:NP-91",
            "column": "ih_clear_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 240.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:NP-91:ih_clear_value_inr",
          "text": "Training Bites (old pack): cost of the units to clear",
          "value": 15840.0,
          "metric": "ih_clear_value_inr",
          "unit": "inr",
          "sku_key": "E003:NP-91",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003:NP-91",
            "column": "ih_clear_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 15840.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:dead:NP-91:ih_days_since_sale",
          "text": "Training Bites (old pack): days since the last sale",
          "value": 116.0,
          "metric": "ih_days_since_sale",
          "unit": "units",
          "sku_key": "E003:NP-91",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E003:NP-91",
            "column": "ih_days_since_sale"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 116.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 240,
        "daily_demand": 0.0,
        "cover_days": null,
        "inbound_units": 0,
        "cover_inbound_days": null,
        "run_out_day": null,
        "short_days": 0.0,
        "lead_time_days": 6,
        "moq_units": 100,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [],
        "stock_value_inr": 15840.0,
        "days_since_sale": 116,
        "oldest_age_days": 167,
        "aged_units": 240,
        "terms": {
          "return_terms": "sell_or_return",
          "return_window_ends": "2026-12-31",
          "restocking_fee_pct": 5.0
        },
        "legacy": true,
        "band_state": "not_moving"
      },
      "note": "The vendor takes this back under sell-or-return for ₹15,048 of credit, with 66 days left in the window.",
      "email_id": "DR-IH-E003",
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:aged:TW-05",
      "sku_code": "TW-05",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Printed Bandana Set",
      "category": "treats",
      "legacy": false,
      "kind": "aged",
      "recommendation": "return_to_vendor",
      "severity": "high",
      "reasons": [
        "343 units are older than 90 days (oldest 150 days). Cover is 260 days, 337 units above the 30-day target.",
        "Sell-or-return terms are open until 2026-11-13 (18 days). A promo would take 117.5 days to clear it, over the 90 days the playbook allows: return the stock for ₹35,844 of credit.",
        "The window closes soon: raise the return now."
      ],
      "clear": {
        "kind": "aged",
        "units": 343,
        "excess_units": 337,
        "aged_units": 343,
        "value_inr": 37730.0,
        "liquidate": {
          "units": 343,
          "discount_pct": 0.25,
          "price_inr": 137.0,
          "recovery_inr": 46991.0,
          "write_down_inr": -9261.0,
          "clear_days": 117.5,
          "floor_applied": false
        },
        "rtv": {
          "units": 343,
          "credit_inr": 35843.5,
          "days_left": 18,
          "window_ends": "2026-11-13",
          "open": true,
          "urgent": true,
          "restocking_fee_pct": 5.0
        }
      },
      "claims": [
        {
          "id": "ih:aged:TW-05:ih_on_hand_units",
          "text": "Printed Bandana Set: units on hand",
          "value": 381.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E004:TW-05",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-05",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 381.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-05:ih_stock_value_inr",
          "text": "Printed Bandana Set: stock at cost",
          "value": 41910.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E004:TW-05",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-05",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 41910.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-05:ih_daily_demand",
          "text": "Printed Bandana Set: forecast units a day",
          "value": 1.46,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E004:TW-05",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-05",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 1.46,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-05:ih_cover_days",
          "text": "Printed Bandana Set: days of cover on hand",
          "value": 260.2,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E004:TW-05",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-05",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 260.2,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-05:ih_clear_units",
          "text": "Printed Bandana Set: units to clear",
          "value": 343.0,
          "metric": "ih_clear_units",
          "unit": "units",
          "sku_key": "E004:TW-05",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-05",
            "column": "ih_clear_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 343.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 381,
        "daily_demand": 1.46,
        "cover_days": 260.2,
        "inbound_units": 0,
        "cover_inbound_days": 260.2,
        "run_out_day": 260.2,
        "short_days": 0.0,
        "lead_time_days": 14,
        "moq_units": 300,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [],
        "stock_value_inr": 41910.0,
        "days_since_sale": 1,
        "oldest_age_days": 150,
        "aged_units": 343,
        "terms": {
          "return_terms": "sell_or_return",
          "return_window_ends": "2026-11-13",
          "restocking_fee_pct": 5.0
        },
        "legacy": false,
        "band_state": "above"
      },
      "note": null,
      "email_id": "DR-IH-E004",
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:stock_out:LT-03",
      "sku_code": "LT-03",
      "vendor_id": "E005",
      "brand": "Litterly",
      "name": "Tofu Litter Original 6 L",
      "category": "cat litter",
      "legacy": false,
      "kind": "stock_out",
      "recommendation": "reorder",
      "severity": "medium",
      "reasons": [
        "Cover including inbound is 19.7 days, under the 20.0 days that lead time (8), the review cycle and safety stock need. Order 280 units now to reach 30 days of cover when it lands."
      ],
      "reorder": {
        "qty": 280,
        "needed_units": 221,
        "moq_units": 140,
        "lead_time_days": 8,
        "order_by": "2026-10-26",
        "cost_inr": 106400.0,
        "overbuy_units": 59,
        "moq_driven": false
      },
      "claims": [
        {
          "id": "ih:stock_out:LT-03:ih_on_hand_units",
          "text": "Tofu Litter Original 6 L: units on hand",
          "value": 238.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E005:LT-03",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E005:LT-03",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 238.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-03:ih_stock_value_inr",
          "text": "Tofu Litter Original 6 L: stock at cost",
          "value": 90440.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E005:LT-03",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E005:LT-03",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 90440.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-03:ih_daily_demand",
          "text": "Tofu Litter Original 6 L: forecast units a day",
          "value": 12.07,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E005:LT-03",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E005:LT-03",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 12.07,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-03:ih_cover_days",
          "text": "Tofu Litter Original 6 L: days of cover on hand",
          "value": 19.72,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E005:LT-03",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E005:LT-03",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 19.72,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:stock_out:LT-03:ih_lead_time_days",
          "text": "Tofu Litter Original 6 L: vendor lead time",
          "value": 8.0,
          "metric": "ih_lead_time_days",
          "unit": "units",
          "sku_key": "E005:LT-03",
          "source_ref": {
            "file": "ops/vendors.json",
            "key": "E005:LT-03",
            "column": "ih_lead_time_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 8.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 238,
        "daily_demand": 12.07,
        "cover_days": 19.72,
        "inbound_units": 0,
        "cover_inbound_days": 19.72,
        "run_out_day": 19.72,
        "short_days": 0.0,
        "lead_time_days": 8,
        "moq_units": 140,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [],
        "stock_value_inr": 90440.0,
        "days_since_sale": 1,
        "oldest_age_days": 45,
        "aged_units": 0,
        "terms": {
          "return_terms": "none",
          "return_window_ends": null,
          "restocking_fee_pct": 0.0
        },
        "legacy": false,
        "band_state": "in"
      },
      "note": null,
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:overbuy:TW-06",
      "sku_code": "TW-06",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Collapsible Travel Bowl",
      "category": "accessories",
      "legacy": false,
      "kind": "overbuy",
      "recommendation": "pause_po",
      "severity": "medium",
      "reasons": [
        "Cover with the open PO would be 63.8 days, over the 60-day ceiling; without it, 30.0 days, which is healthy.",
        "The PO is 300 units against 124 needed: the vendor's minimum order quantity of 300 forces an overbuy of 176 units."
      ],
      "pause": {
        "po_id": "PO-E004-0007",
        "pause_units": 300,
        "promised": "2026-10-27",
        "arrives_in_days": 1.0,
        "cover_without_po_days": 30.03,
        "cover_with_po_days": 63.76,
        "needed_units": 124,
        "overbuy_units": 176,
        "moq_units": 300,
        "moq_driven": true,
        "value_inr": 42000.0
      },
      "claims": [
        {
          "id": "ih:overbuy:TW-06:ih_on_hand_units",
          "text": "Collapsible Travel Bowl: units on hand",
          "value": 267.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E004:TW-06",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-06",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 267.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:overbuy:TW-06:ih_stock_value_inr",
          "text": "Collapsible Travel Bowl: stock at cost",
          "value": 37380.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E004:TW-06",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-06",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 37380.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:overbuy:TW-06:ih_daily_demand",
          "text": "Collapsible Travel Bowl: forecast units a day",
          "value": 8.89,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E004:TW-06",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-06",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 8.89,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:overbuy:TW-06:ih_cover_days",
          "text": "Collapsible Travel Bowl: days of cover on hand",
          "value": 30.02,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E004:TW-06",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-06",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 30.02,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:overbuy:TW-06:ih_inbound_units",
          "text": "Collapsible Travel Bowl: units on open POs",
          "value": 300.0,
          "metric": "ih_inbound_units",
          "unit": "units",
          "sku_key": "E004:TW-06",
          "source_ref": {
            "file": "ops/purchase_orders.csv",
            "key": "E004:TW-06",
            "column": "ih_inbound_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 300.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 267,
        "daily_demand": 8.89,
        "cover_days": 30.02,
        "inbound_units": 300,
        "cover_inbound_days": 63.76,
        "run_out_day": 63.76,
        "short_days": 0.0,
        "lead_time_days": 14,
        "moq_units": 300,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [
          {
            "po_id": "PO-E004-0007",
            "qty": 300,
            "promised": "2026-10-27",
            "arrives_in_days": 1.0,
            "overdue": false,
            "received": 0,
            "ordered": 300
          }
        ],
        "stock_value_inr": 37380.0,
        "days_since_sale": 1,
        "oldest_age_days": 49,
        "aged_units": 0,
        "terms": {
          "return_terms": "none",
          "return_window_ends": null,
          "restocking_fee_pct": 0.0
        },
        "legacy": false,
        "band_state": "in"
      },
      "note": "Without the open PO there are still 30.03 days of cover. Hold the 300 units.",
      "email_id": "DR-IH-E004",
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:aged:TW-04",
      "sku_code": "TW-04",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Adjustable Harness Medium",
      "category": "accessories",
      "legacy": false,
      "kind": "aged",
      "recommendation": "liquidate",
      "severity": "medium",
      "reasons": [
        "198 units are older than 90 days (oldest 118 days). Cover is 140 days, 283 units above the 30-day target.",
        "No sell-or-return terms on file for this SKU: clear it with a promo."
      ],
      "clear": {
        "kind": "aged",
        "units": 283,
        "excess_units": 283,
        "aged_units": 198,
        "value_inr": 101880.0,
        "liquidate": {
          "units": 283,
          "discount_pct": 0.25,
          "price_inr": 413.0,
          "recovery_inr": 116879.0,
          "write_down_inr": -14999.0,
          "clear_days": 55.1,
          "floor_applied": false
        },
        "rtv": null
      },
      "claims": [
        {
          "id": "ih:aged:TW-04:ih_on_hand_units",
          "text": "Adjustable Harness Medium: units on hand",
          "value": 360.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E004:TW-04",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-04",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 360.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-04:ih_stock_value_inr",
          "text": "Adjustable Harness Medium: stock at cost",
          "value": 129600.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E004:TW-04",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-04",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 129600.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-04:ih_daily_demand",
          "text": "Adjustable Harness Medium: forecast units a day",
          "value": 2.57,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E004:TW-04",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-04",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 2.57,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-04:ih_cover_days",
          "text": "Adjustable Harness Medium: days of cover on hand",
          "value": 140.0,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E004:TW-04",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-04",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 140.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-04:ih_clear_units",
          "text": "Adjustable Harness Medium: units to clear",
          "value": 283.0,
          "metric": "ih_clear_units",
          "unit": "units",
          "sku_key": "E004:TW-04",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-04",
            "column": "ih_clear_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 283.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 360,
        "daily_demand": 2.57,
        "cover_days": 140.0,
        "inbound_units": 0,
        "cover_inbound_days": 140.0,
        "run_out_day": 140.0,
        "short_days": 0.0,
        "lead_time_days": 14,
        "moq_units": 300,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [],
        "stock_value_inr": 129600.0,
        "days_since_sale": 1,
        "oldest_age_days": 118,
        "aged_units": 198,
        "terms": {
          "return_terms": "none",
          "return_window_ends": null,
          "restocking_fee_pct": 0.0
        },
        "legacy": false,
        "band_state": "above"
      },
      "note": null,
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    },
    {
      "id": "ih:aged:TW-03",
      "sku_code": "TW-03",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Feather Wand Teaser",
      "category": "toys",
      "legacy": false,
      "kind": "aged",
      "recommendation": "liquidate",
      "severity": "medium",
      "reasons": [
        "170 units are older than 90 days (oldest 130 days). Cover is 150 days, 227 units above the 30-day target.",
        "The sell-or-return window closed on 2026-10-10: clear it with a promo."
      ],
      "clear": {
        "kind": "aged",
        "units": 227,
        "excess_units": 227,
        "aged_units": 170,
        "value_inr": 34050.0,
        "liquidate": {
          "units": 227,
          "discount_pct": 0.25,
          "price_inr": 172.0,
          "recovery_inr": 39044.0,
          "write_down_inr": -4994.0,
          "clear_days": 60.1,
          "floor_applied": false
        },
        "rtv": {
          "units": 227,
          "credit_inr": 32347.5,
          "days_left": -16,
          "window_ends": "2026-10-10",
          "open": false,
          "urgent": false,
          "restocking_fee_pct": 5.0
        }
      },
      "claims": [
        {
          "id": "ih:aged:TW-03:ih_on_hand_units",
          "text": "Feather Wand Teaser: units on hand",
          "value": 284.0,
          "metric": "ih_on_hand_units",
          "unit": "units",
          "sku_key": "E004:TW-03",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-03",
            "column": "ih_on_hand_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 284.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-03:ih_stock_value_inr",
          "text": "Feather Wand Teaser: stock at cost",
          "value": 42600.0,
          "metric": "ih_stock_value_inr",
          "unit": "inr",
          "sku_key": "E004:TW-03",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-03",
            "column": "ih_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 42600.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-03:ih_daily_demand",
          "text": "Feather Wand Teaser: forecast units a day",
          "value": 1.89,
          "metric": "ih_daily_demand",
          "unit": "ratio",
          "sku_key": "E004:TW-03",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-03",
            "column": "ih_daily_demand"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 1.89,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-03:ih_cover_days",
          "text": "Feather Wand Teaser: days of cover on hand",
          "value": 150.04,
          "metric": "ih_cover_days",
          "unit": "ratio",
          "sku_key": "E004:TW-03",
          "source_ref": {
            "file": "ops/sales_daily.csv",
            "key": "E004:TW-03",
            "column": "ih_cover_days"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 150.04,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ih:aged:TW-03:ih_clear_units",
          "text": "Feather Wand Teaser: units to clear",
          "value": 227.0,
          "metric": "ih_clear_units",
          "unit": "units",
          "sku_key": "E004:TW-03",
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004:TW-03",
            "column": "ih_clear_units"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 227.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ],
      "stock": {
        "on_hand": 284,
        "daily_demand": 1.89,
        "cover_days": 150.04,
        "inbound_units": 0,
        "cover_inbound_days": 150.04,
        "run_out_day": 150.04,
        "short_days": 0.0,
        "lead_time_days": 14,
        "moq_units": 300,
        "band": {
          "min_days": 14.0,
          "target_days": 30.0,
          "max_days": 60.0
        },
        "landings": [],
        "stock_value_inr": 42600.0,
        "days_since_sale": 1,
        "oldest_age_days": 130,
        "aged_units": 170,
        "terms": {
          "return_terms": "sell_or_return",
          "return_window_ends": "2026-10-10",
          "restocking_fee_pct": 5.0
        },
        "legacy": false,
        "band_state": "above"
      },
      "note": null,
      "email_id": null,
      "decision": {
        "status": "pending"
      }
    }
  ],
  "vendors": [
    {
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "skus": 6,
      "stock_value_inr": 925184.0,
      "stuck_value_inr": 0,
      "stockout_skus": 0,
      "actions": 0,
      "lead_time_days": 7,
      "claims": [
        {
          "id": "ihv:E001:ih_vendor_stock_value_inr",
          "text": "Barkley & Co: stock at cost",
          "value": 925184.0,
          "metric": "ih_vendor_stock_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E001",
            "column": "ih_vendor_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 925184.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E001:ih_vendor_stuck_value_inr",
          "text": "Barkley & Co: stock to return or clear",
          "value": 0.0,
          "metric": "ih_vendor_stuck_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E001",
            "column": "ih_vendor_stuck_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 0.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E001:ih_vendor_stockout_skus",
          "text": "Barkley & Co: SKUs at risk of a stock-out",
          "value": 0.0,
          "metric": "ih_vendor_stockout_skus",
          "unit": "units",
          "sku_key": null,
          "source_ref": {
            "file": "ops/purchase_orders.csv",
            "key": "E001",
            "column": "ih_vendor_stockout_skus"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 0.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ]
    },
    {
      "vendor_id": "E002",
      "brand": "Purrline Foods",
      "skus": 6,
      "stock_value_inr": 553515.0,
      "stuck_value_inr": 0.0,
      "stockout_skus": 1,
      "actions": 1,
      "lead_time_days": 10,
      "claims": [
        {
          "id": "ihv:E002:ih_vendor_stock_value_inr",
          "text": "Purrline Foods: stock at cost",
          "value": 553515.0,
          "metric": "ih_vendor_stock_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E002",
            "column": "ih_vendor_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 553515.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E002:ih_vendor_stuck_value_inr",
          "text": "Purrline Foods: stock to return or clear",
          "value": 0.0,
          "metric": "ih_vendor_stuck_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E002",
            "column": "ih_vendor_stuck_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 0.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E002:ih_vendor_stockout_skus",
          "text": "Purrline Foods: SKUs at risk of a stock-out",
          "value": 1.0,
          "metric": "ih_vendor_stockout_skus",
          "unit": "units",
          "sku_key": null,
          "source_ref": {
            "file": "ops/purchase_orders.csv",
            "key": "E002",
            "column": "ih_vendor_stockout_skus"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 1.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ]
    },
    {
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "skus": 7,
      "stock_value_inr": 380618.0,
      "stuck_value_inr": 15840.0,
      "stockout_skus": 1,
      "actions": 2,
      "lead_time_days": 6,
      "claims": [
        {
          "id": "ihv:E003:ih_vendor_stock_value_inr",
          "text": "NutriPaws: stock at cost",
          "value": 380618.0,
          "metric": "ih_vendor_stock_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003",
            "column": "ih_vendor_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 380618.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E003:ih_vendor_stuck_value_inr",
          "text": "NutriPaws: stock to return or clear",
          "value": 15840.0,
          "metric": "ih_vendor_stuck_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E003",
            "column": "ih_vendor_stuck_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 15840.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E003:ih_vendor_stockout_skus",
          "text": "NutriPaws: SKUs at risk of a stock-out",
          "value": 1.0,
          "metric": "ih_vendor_stockout_skus",
          "unit": "units",
          "sku_key": null,
          "source_ref": {
            "file": "ops/purchase_orders.csv",
            "key": "E003",
            "column": "ih_vendor_stockout_skus"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 1.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ]
    },
    {
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "skus": 6,
      "stock_value_inr": 317250.0,
      "stuck_value_inr": 173660.0,
      "stockout_skus": 0,
      "actions": 4,
      "lead_time_days": 14,
      "claims": [
        {
          "id": "ihv:E004:ih_vendor_stock_value_inr",
          "text": "Tailwind Play: stock at cost",
          "value": 317250.0,
          "metric": "ih_vendor_stock_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004",
            "column": "ih_vendor_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 317250.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E004:ih_vendor_stuck_value_inr",
          "text": "Tailwind Play: stock to return or clear",
          "value": 173660.0,
          "metric": "ih_vendor_stuck_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E004",
            "column": "ih_vendor_stuck_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 173660.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E004:ih_vendor_stockout_skus",
          "text": "Tailwind Play: SKUs at risk of a stock-out",
          "value": 0.0,
          "metric": "ih_vendor_stockout_skus",
          "unit": "units",
          "sku_key": null,
          "source_ref": {
            "file": "ops/purchase_orders.csv",
            "key": "E004",
            "column": "ih_vendor_stockout_skus"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 0.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ]
    },
    {
      "vendor_id": "E005",
      "brand": "Litterly",
      "skus": 6,
      "stock_value_inr": 883435.0,
      "stuck_value_inr": 0.0,
      "stockout_skus": 2,
      "actions": 2,
      "lead_time_days": 8,
      "claims": [
        {
          "id": "ihv:E005:ih_vendor_stock_value_inr",
          "text": "Litterly: stock at cost",
          "value": 883435.0,
          "metric": "ih_vendor_stock_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E005",
            "column": "ih_vendor_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 883435.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E005:ih_vendor_stuck_value_inr",
          "text": "Litterly: stock to return or clear",
          "value": 0.0,
          "metric": "ih_vendor_stuck_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E005",
            "column": "ih_vendor_stuck_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 0.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E005:ih_vendor_stockout_skus",
          "text": "Litterly: SKUs at risk of a stock-out",
          "value": 2.0,
          "metric": "ih_vendor_stockout_skus",
          "unit": "units",
          "sku_key": null,
          "source_ref": {
            "file": "ops/purchase_orders.csv",
            "key": "E005",
            "column": "ih_vendor_stockout_skus"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 2.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ]
    },
    {
      "vendor_id": "E006",
      "brand": "Groomwell",
      "skus": 7,
      "stock_value_inr": 275745.0,
      "stuck_value_inr": 21240.0,
      "stockout_skus": 0,
      "actions": 1,
      "lead_time_days": 9,
      "claims": [
        {
          "id": "ihv:E006:ih_vendor_stock_value_inr",
          "text": "Groomwell: stock at cost",
          "value": 275745.0,
          "metric": "ih_vendor_stock_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E006",
            "column": "ih_vendor_stock_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 275745.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E006:ih_vendor_stuck_value_inr",
          "text": "Groomwell: stock to return or clear",
          "value": 21240.0,
          "metric": "ih_vendor_stuck_value_inr",
          "unit": "inr",
          "sku_key": null,
          "source_ref": {
            "file": "ops/inventory_batches.csv",
            "key": "E006",
            "column": "ih_vendor_stuck_value_inr"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 21240.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        },
        {
          "id": "ihv:E006:ih_vendor_stockout_skus",
          "text": "Groomwell: SKUs at risk of a stock-out",
          "value": 0.0,
          "metric": "ih_vendor_stockout_skus",
          "unit": "units",
          "sku_key": null,
          "source_ref": {
            "file": "ops/purchase_orders.csv",
            "key": "E006",
            "column": "ih_vendor_stockout_skus"
          },
          "origin": "engine",
          "status": "verified",
          "recomputed": 0.0,
          "reason": null,
          "attempts": [],
          "evidence": null
        }
      ]
    }
  ],
  "skus": [
    {
      "sku_code": "PL-01",
      "vendor_id": "E002",
      "brand": "Purrline Foods",
      "name": "Ocean Fish Adult 1.2 kg",
      "legacy": false,
      "on_hand": 96,
      "daily_demand": 15.93,
      "cover_days": 6.03,
      "inbound_units": 500,
      "cover_inbound_days": 38.39,
      "stock_value_inr": 43200.0,
      "days_since_sale": 1,
      "band_state": "below",
      "kind": "stock_out",
      "recommendation": "expedite_po"
    },
    {
      "sku_code": "NP-03",
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "name": "Peanut Butter Biscuits 400 g",
      "legacy": false,
      "on_hand": 22,
      "daily_demand": 57.46,
      "cover_days": 0.38,
      "inbound_units": 600,
      "cover_inbound_days": 17.44,
      "stock_value_inr": 7260.0,
      "days_since_sale": 1,
      "band_state": "below",
      "kind": "stock_out",
      "recommendation": "reorder"
    },
    {
      "sku_code": "NP-91",
      "vendor_id": "E003",
      "brand": "NutriPaws",
      "name": "Training Bites (old pack)",
      "legacy": true,
      "on_hand": 240,
      "daily_demand": 0.0,
      "cover_days": null,
      "inbound_units": 0,
      "cover_inbound_days": null,
      "stock_value_inr": 15840.0,
      "days_since_sale": 116,
      "band_state": "not_moving",
      "kind": "dead",
      "recommendation": "return_to_vendor"
    },
    {
      "sku_code": "TW-03",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Feather Wand Teaser",
      "legacy": false,
      "on_hand": 284,
      "daily_demand": 1.89,
      "cover_days": 150.04,
      "inbound_units": 0,
      "cover_inbound_days": 150.04,
      "stock_value_inr": 42600.0,
      "days_since_sale": 1,
      "band_state": "above",
      "kind": "aged",
      "recommendation": "liquidate"
    },
    {
      "sku_code": "TW-04",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Adjustable Harness Medium",
      "legacy": false,
      "on_hand": 360,
      "daily_demand": 2.57,
      "cover_days": 140.0,
      "inbound_units": 0,
      "cover_inbound_days": 140.0,
      "stock_value_inr": 129600.0,
      "days_since_sale": 1,
      "band_state": "above",
      "kind": "aged",
      "recommendation": "liquidate"
    },
    {
      "sku_code": "TW-05",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Printed Bandana Set",
      "legacy": false,
      "on_hand": 381,
      "daily_demand": 1.46,
      "cover_days": 260.2,
      "inbound_units": 0,
      "cover_inbound_days": 260.2,
      "stock_value_inr": 41910.0,
      "days_since_sale": 1,
      "band_state": "above",
      "kind": "aged",
      "recommendation": "return_to_vendor"
    },
    {
      "sku_code": "TW-06",
      "vendor_id": "E004",
      "brand": "Tailwind Play",
      "name": "Collapsible Travel Bowl",
      "legacy": false,
      "on_hand": 267,
      "daily_demand": 8.89,
      "cover_days": 30.02,
      "inbound_units": 300,
      "cover_inbound_days": 63.76,
      "stock_value_inr": 37380.0,
      "days_since_sale": 1,
      "band_state": "in",
      "kind": "overbuy",
      "recommendation": "pause_po"
    },
    {
      "sku_code": "LT-03",
      "vendor_id": "E005",
      "brand": "Litterly",
      "name": "Tofu Litter Original 6 L",
      "legacy": false,
      "on_hand": 238,
      "daily_demand": 12.07,
      "cover_days": 19.72,
      "inbound_units": 0,
      "cover_inbound_days": 19.72,
      "stock_value_inr": 90440.0,
      "days_since_sale": 1,
      "band_state": "in",
      "kind": "stock_out",
      "recommendation": "reorder"
    },
    {
      "sku_code": "LT-05",
      "vendor_id": "E005",
      "brand": "Litterly",
      "name": "Clumping Bentonite 5 kg",
      "legacy": false,
      "on_hand": 142,
      "daily_demand": 28.5,
      "cover_days": 4.98,
      "inbound_units": 700,
      "cover_inbound_days": 31.56,
      "stock_value_inr": 39050.0,
      "days_since_sale": 1,
      "band_state": "below",
      "kind": "stock_out",
      "recommendation": "expedite_po"
    },
    {
      "sku_code": "GW-91",
      "vendor_id": "E006",
      "brand": "Groomwell",
      "name": "Oatmeal Shampoo (old label)",
      "legacy": true,
      "on_hand": 180,
      "daily_demand": 0.0,
      "cover_days": null,
      "inbound_units": 0,
      "cover_inbound_days": null,
      "stock_value_inr": 21240.0,
      "days_since_sale": 100,
      "band_state": "not_moving",
      "kind": "dead",
      "recommendation": "liquidate"
    },
    {
      "sku_code": "BK-01",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Chicken & Rice Adult 3 kg",
      "legacy": false,
      "on_hand": 382,
      "daily_demand": 14.32,
      "cover_days": 26.67,
      "inbound_units": 400,
      "cover_inbound_days": 54.6,
      "stock_value_inr": 290320.0,
      "days_since_sale": 1,
      "band_state": "in",
      "kind": null,
      "recommendation": null
    },
    {
      "sku_code": "BK-02",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Lamb & Rice Adult 3 kg",
      "legacy": false,
      "on_hand": 337,
      "daily_demand": 11.11,
      "cover_days": 30.34,
      "inbound_units": 0,
      "cover_inbound_days": 30.34,
      "stock_value_inr": 269600.0,
      "days_since_sale": 1,
      "band_state": "in",
      "kind": null,
      "recommendation": null
    },
    {
      "sku_code": "BK-03",
      "vendor_id": "E001",
      "brand": "Barkley & Co",
      "name": "Puppy Starter 1 kg",
      "legacy": false,
      "on_hand": 553,
      "daily_demand": 19.0,
      "cover_days": 29.11,
      "inbound_units": 0,
      "cover_inbound_days": 29.11,
      "stock_value_inr": 165900.0,
      "days_since_sale": 1,
      "band_state": "in",
      "kind": null,
      "recommendation": null
    }
  ],
  "drafts": [
    {
      "id": "DR-IH-E002",
      "kind": "inventory_health",
      "channel": "email",
      "subject": "Inventory review: Purrline Foods",
      "body": "Hi Rakesh,\n\nOcean Fish Adult 1.2 kg runs out in 6.0 days, and its open PO (500 units) is past its promised date, so we expect about 1.0 days out of stock. Please confirm dispatch and ship it by Friday.\n\nPlease let us know by Friday.\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E002:0",
          "shown": "6.0",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E002:1",
          "shown": "1.0",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E002:2",
          "shown": "500",
          "status": "verified",
          "reason": null
        }
      ],
      "claim_ids": [
        "fig:email:E002:0",
        "fig:email:E002:1",
        "fig:email:E002:2"
      ],
      "vendor_id": "E002",
      "po_id": null,
      "to": "dispatch@purrline.example",
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
      "id": "DR-IH-E003",
      "kind": "inventory_health",
      "channel": "email",
      "subject": "Inventory review: NutriPaws",
      "body": "Hi Meera,\n\nUnder our sell-or-return terms we would like to return 240 units of Training Bites (old pack) for ₹15,048 of credit. The window closes in 66 days; please send a return authorisation.\n\nPlease let us know by Friday.\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E003:0",
          "shown": "240",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E003:1",
          "shown": "₹15,048",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E003:2",
          "shown": "66",
          "status": "verified",
          "reason": null
        }
      ],
      "claim_ids": [
        "fig:email:E003:0",
        "fig:email:E003:1",
        "fig:email:E003:2"
      ],
      "vendor_id": "E003",
      "po_id": null,
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
    },
    {
      "id": "DR-IH-E004",
      "kind": "inventory_health",
      "channel": "email",
      "subject": "Inventory review: Tailwind Play",
      "body": "Hi Vikram,\n\nUnder our sell-or-return terms we would like to return 343 units of Printed Bandana Set for ₹35,844 of credit. The window closes in 18 days; please send a return authorisation.\nPlease hold PO PO-E004-0007 for Collapsible Travel Bowl (300 units). We already hold 30.0 days of cover without it, and the minimum order quantity of 300 made the PO larger than we need. We will take it in the next cycle.\n\nPlease let us know by Friday.\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E004:0",
          "shown": "343",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E004:1",
          "shown": "₹35,844",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E004:2",
          "shown": "18",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E004:3",
          "shown": "300",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E004:4",
          "shown": "30.0",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E004:5",
          "shown": "300",
          "status": "verified",
          "reason": null
        }
      ],
      "claim_ids": [
        "fig:email:E004:0",
        "fig:email:E004:1",
        "fig:email:E004:2",
        "fig:email:E004:3",
        "fig:email:E004:4",
        "fig:email:E004:5"
      ],
      "vendor_id": "E004",
      "po_id": null,
      "to": "sales@tailwindplay.example",
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
      "id": "DR-IH-E005",
      "kind": "inventory_health",
      "channel": "email",
      "subject": "Inventory review: Litterly",
      "body": "Hi Sanjay,\n\nClumping Bentonite 5 kg runs out in 5.0 days, and its open PO (700 units) is past its promised date, so we expect about 2.0 days out of stock. Please confirm dispatch and ship it by Friday.\n\nPlease let us know by Friday.\n\nThanks",
      "source": "agent",
      "figures": [
        {
          "claim_id": "fig:email:E005:0",
          "shown": "5.0",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E005:1",
          "shown": "2.0",
          "status": "verified",
          "reason": null
        },
        {
          "claim_id": "fig:email:E005:2",
          "shown": "700",
          "status": "verified",
          "reason": null
        }
      ],
      "claim_ids": [
        "fig:email:E005:0",
        "fig:email:E005:1",
        "fig:email:E005:2"
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
      "text": "Peanut Butter Biscuits 400 g: days until the stock runs out",
      "value": 0.38,
      "metric": "ih_run_out_day",
      "unit": "ratio",
      "sku_key": "E003:NP-03",
      "source_ref": {
        "file": "ops/purchase_orders.csv",
        "key": "E003:NP-03",
        "column": "ih_run_out_day"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 0.38,
      "reason": null,
      "attempts": [],
      "evidence": null
    },
    {
      "id": "fig:brief:1",
      "text": "Peanut Butter Biscuits 400 g: units to order",
      "value": 1800.0,
      "metric": "ih_reorder_qty",
      "unit": "units",
      "sku_key": "E003:NP-03",
      "source_ref": {
        "file": "ops/inventory_terms.csv",
        "key": "E003:NP-03",
        "column": "ih_reorder_qty"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 1800.0,
      "reason": null,
      "attempts": [],
      "evidence": null
    },
    {
      "id": "fig:brief:2",
      "text": "Peanut Butter Biscuits 400 g: cost of the order",
      "value": 594000.0,
      "metric": "ih_reorder_cost_inr",
      "unit": "inr",
      "sku_key": "E003:NP-03",
      "source_ref": {
        "file": "ops/inventory_terms.csv",
        "key": "E003:NP-03",
        "column": "ih_reorder_cost_inr"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 594000.0,
      "reason": null,
      "attempts": [],
      "evidence": null
    },
    {
      "id": "fig:brief:3",
      "text": "Clumping Bentonite 5 kg: days until the stock runs out",
      "value": 4.98,
      "metric": "ih_run_out_day",
      "unit": "ratio",
      "sku_key": "E005:LT-05",
      "source_ref": {
        "file": "ops/purchase_orders.csv",
        "key": "E005:LT-05",
        "column": "ih_run_out_day"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 4.98,
      "reason": null,
      "attempts": [],
      "evidence": null
    },
    {
      "id": "fig:brief:4",
      "text": "Clumping Bentonite 5 kg: days out of stock",
      "value": 2.02,
      "metric": "ih_short_days",
      "unit": "ratio",
      "sku_key": "E005:LT-05",
      "source_ref": {
        "file": "ops/purchase_orders.csv",
        "key": "E005:LT-05",
        "column": "ih_short_days"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 2.02,
      "reason": null,
      "attempts": [],
      "evidence": null
    },
    {
      "id": "fig:brief:5",
      "text": "Collapsible Travel Bowl: units on the PO to pause",
      "value": 300.0,
      "metric": "ih_pause_units",
      "unit": "units",
      "sku_key": "E004:TW-06",
      "source_ref": {
        "file": "ops/purchase_orders.csv",
        "key": "E004:TW-06",
        "column": "ih_pause_units"
      },
      "origin": "engine",
      "status": "verified",
      "recomputed": 300.0,
      "reason": null,
      "attempts": [],
      "evidence": null
    }
  ],
  "verification": {
    "total": 184,
    "verified": 184,
    "rejected": 0,
    "unverifiable": 0
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
        "task": "inventory_health",
        "as_of": "2026-10-26",
        "skus": 38
      }
    },
    {
      "seq": 2,
      "t_rel_ms": 68.2,
      "type": "tool_call",
      "stage": "ops",
      "model": null,
      "latency_ms": 67.79,
      "cost_usd": null,
      "payload": {
        "tool": "get_inventory_summary",
        "args": {},
        "result_summary": "as_of=2026-10-26, counts{16}, actions[10], vendors[6]"
      }
    },
    {
      "seq": 3,
      "t_rel_ms": 68.5,
      "type": "model_call",
      "stage": "ops",
      "model": "muse-spark-1.3",
      "latency_ms": 68.346,
      "cost_usd": 0.0,
      "payload": {
        "task": "ih_brief",
        "mode": "mock",
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_steps": 1
      }
    },
    {
      "seq": 4,
      "t_rel_ms": 136.0,
      "type": "tool_call",
      "stage": "ops",
      "model": null,
      "latency_ms": 66.61,
      "cost_usd": null,
      "payload": {
        "tool": "get_inventory_summary",
        "args": {},
        "result_summary": "as_of=2026-10-26, counts{16}, actions[10], vendors[6]"
      }
    },
    {
      "seq": 5,
      "t_rel_ms": 136.0,
      "type": "tool_call",
      "stage": "ops",
      "model": null,
      "latency_ms": 0.008,
      "cost_usd": null,
      "payload": {
        "tool": "get_vendor_contacts",
        "args": {},
        "result_summary": "vendors[6]"
      }
    },
    {
      "seq": 6,
      "t_rel_ms": 136.1,
      "type": "model_call",
      "stage": "ops",
      "model": "muse-spark-1.3",
      "latency_ms": 67.568,
      "cost_usd": 0.0,
      "payload": {
        "task": "ih_vendor_emails",
        "mode": "mock",
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_steps": 2
      }
    }
  ],
  "thresholds": {
    "cover_min_days": 14.0,
    "cover_target_days": 30.0,
    "cover_max_days": 60.0,
    "aged_days": 90,
    "dead_no_sale_days": 45,
    "critical_days": 3.0,
    "safety_days": 5.0,
    "review_days": 7.0,
    "overdue_assumed_days": 7.0,
    "overbuy_ratio": 1.5,
    "rtv_urgent_window_days": 21,
    "max_clear_days": 90.0,
    "forecast_window_days": 28
  },
  "impact_coverage": {
    "module": "inventory_health_module",
    "registered": true,
    "status": "shipped",
    "tasks": [
      {
        "task": "inventory_health",
        "in_scope_pct": 100.0
      }
    ],
    "units": {
      "inventory_ageing_review": 1
    },
    "baseline_minutes": {
      "inventory_ageing_review": 180.0
    },
    "manual_minutes_replaced": 180.0,
    "baseline_status": "research_estimate"
  },
  "decisions": []
};

export const inventoryHealth = (): InventoryHealth => structuredClone(REVIEW) as unknown as InventoryHealth;

export const reorderApproved: IhDecisionResult = {
  action_id: "ih:stock_out:NP-03",
  status: "approved",
  decided_at: "2026-10-27T17:49:35+00:00",
  note: null,
  simulated: true,
  effect: { type: "po_draft", sku_code: "NP-03", vendor_id: "E003", qty: 1800, lead_time_days: 6, lands_on: "2026-11-01" },
  recommendation: "reorder",
};

export const returnApproved: IhDecisionResult = {
  "action_id": "ih:aged:TW-05",
  "status": "approved",
  "decided_at": "2026-10-27T17:49:35+00:00",
  "note": null,
  "simulated": true,
  "effect": {
    "type": "vendor_message",
    "draft_id": "DR-IH-E004",
    "vendor_id": "E004",
    "action": "return_to_vendor",
    "sku_code": "TW-05",
    "units": 343,
    "credit_inr": 35843.5,
    "draft_status": "sent_simulated"
  },
  "recommendation": "return_to_vendor"
} as unknown as IhDecisionResult;

export const liquidateApproved: IhDecisionResult = {
  "action_id": "ih:aged:TW-03",
  "status": "approved",
  "decided_at": "2026-10-27T17:49:35+00:00",
  "note": null,
  "simulated": true,
  "effect": {
    "type": "promo_nomination",
    "sku_code": "TW-03",
    "units": 227,
    "discount_pct": 0.25,
    "price_inr": 172.0
  },
  "recommendation": "liquidate"
} as unknown as IhDecisionResult;
