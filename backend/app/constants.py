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

ROUND_DP = 4
ALLOWED_VENDORS = ("V001", "V002", "V003", "V004")
# Built-in vendors plus sandbox vendors created at /try ("U-" and 8 random lowercase alphanumerics). The pattern only says
# an id is well formed; whether it exists is the registry's call (data_loader.check_vendor).
VENDOR_ID_PATTERN = r"V00[1-9]|U-[a-z0-9]{8}"
