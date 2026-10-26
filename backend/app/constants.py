PHASES = ("screen", "decide", "execute", "launch")

STAGE_META = [
    {"id": "intake", "name": "Intake", "phase": "screen"},
    {"id": "research", "name": "Research", "phase": "decide"},
    {"id": "shortlist", "name": "Shortlist", "phase": "decide"},
    {"id": "negotiate", "name": "Negotiate", "phase": "decide"},
    {"id": "catalog", "name": "Catalog", "phase": "execute"},
    {"id": "marketing", "name": "Marketing", "phase": "launch"},
    {"id": "jbp", "name": "JBP", "phase": "launch"},
    {"id": "po", "name": "PO", "phase": "launch"},
]

METRIC_WEIGHTS = {"margin": 0.4, "demand": 0.3, "overlap": 0.2, "review": 0.1}
DEMAND_MIN = 0.4
OVERLAP_MAX = 0.6
MOQ_FACTOR = 2.0
FREIGHT_PCT = 0.04
TOL = {"pct": 0.01, "inr": 1.0, "units": 0.0, "score": 0.5, "ratio": 0.005, "qty": 0.0}
GST_RATE = 0.18  # placeholder GST shown separately on the PO
MARKETING_MIN_PCT_OF_ORDER = 0.10  # required launch marketing support: 10% of first-order retail value
LAUNCH_DISCOUNT_MIN_PCT = 5.0
DEFECT_RETURN_MIN_DAYS = 7
HERO_SKU_COUNT = 3
PO_LEAD_DAYS = {"confirmed": 2, "shipped": 5, "received": 12}
PO_DELAY_DAYS = 3
ROUND_DP = 4
ALLOWED_VENDORS = ("V001", "V002", "V003", "V004")
