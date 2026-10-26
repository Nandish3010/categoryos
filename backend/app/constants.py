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
TOL = {"pct": 0.01, "inr": 1.0, "units": 0.0, "score": 0.5}
ROUND_DP = 4
ALLOWED_VENDORS = ("V001", "V002", "V003", "V004")
