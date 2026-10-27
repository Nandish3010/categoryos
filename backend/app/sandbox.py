"""Bring your own vendor: create a sandbox vendor from an upload (or a bundled sample), decide how its model stages run,
keep it for a TTL, and clean it up.

Model modes of a sandbox vendor (``llm_mode`` in its meta):
  rules_only  the deterministic engine only, no model call at all (free; what the UI labels "Rules-only (no model calls)")
  mock        the server runs MODEL_MODE=mock: model stages use the generic mock (sandbox_mock), clearly labelled
  live        models may be called: with a valid demo key, or while this IP's per-day budget lasts; the global
              MAX_SPEND_USD cap (ledger.check_budget) always applies

The engine, screening guards and verifier are the same ones the built-in vendors use."""

import asyncio
import csv
import hashlib
import json
import logging
import re
import secrets
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from app import persist, policy, registry, sandbox_budget, scope, uploads
from app.config import settings
from app.errors import CategoryOSError, RateLimited
from app.uploads import ApplicationIn, UploadError

log = logging.getLogger("categoryos.sandbox")

MODE_LABELS = {
    "rules_only": "Rules-only (no model calls)",
    "mock": "Mock model (canned output, not a real model)",
    "live": "Live models",
}
STARTER_LABELS = {
    "pet": "Pet (default playbook)",
    "beauty": "Beauty and personal care",
    "electronics": "Consumer electronics",
}
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_hits: dict[str, deque[float]] = defaultdict(deque)


class SandboxFull(CategoryOSError):
    status = 503
    code = "sandbox_full"
    problem = "The sandbox is full right now"
    cause = "The maximum number of live sandbox vendors is reached"
    fix = "Try again in a few minutes; sandbox vendors expire after their TTL"


class UnknownSample(UploadError):
    status = 404
    code = "unknown_sample"


# ---------- identity of the caller ----------


def client_ip(request: Any) -> str:
    """The caller's address. X-Forwarded-For is trusted only when TRUST_FORWARDED_FOR is set (a proxy in front)."""
    if settings.trust_forwarded_for:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def ip_key(ip: str) -> str:
    return hashlib.sha256(f"categoryos-ip:{ip}".encode()).hexdigest()[:16]


def demo_key_ok(header: str | None) -> bool:
    return bool(settings.demo_key and header and secrets.compare_digest(header.encode(), settings.demo_key.encode()))


def rate_check(ip: str) -> None:
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= settings.upload_rate_per_hour:
        raise RateLimited(
            "Too many uploads from this address",
            cause=f"The limit is {settings.upload_rate_per_hour} per hour",
            fix="Wait a while, or reuse a vendor you already created (they last 24 hours)",
        )
    q.append(now)


def reset_rate_limits() -> None:
    _hits.clear()


# ---------- model mode ----------


def decide_llm_mode(keyed: bool, key: str) -> str:
    """How this vendor's model stages run (see the module docstring). Evaluated at upload and again at run start."""
    if settings.model_mode == "mock":
        return "mock"
    if not settings.model_api_key:
        return "rules_only"
    if keyed:
        return "live"
    if settings.model_mode == "live" and sandbox_budget.remaining(key) > 0:
        return "live"
    return "rules_only"


def authorize_run(request: Any, vendor_id: str, header: str | None) -> None:
    """Called before a run or re-plan on a sandbox vendor. Never raises: a vendor that may no longer call models is
    demoted to rules-only (its documents are then not read), so the run is free and labelled as such."""
    meta = registry.read_meta(vendor_id)
    if meta is None or meta.get("llm_mode") != "live":
        return
    keyed = demo_key_ok(header)
    key = ip_key(client_ip(request))
    mode = decide_llm_mode(keyed, key)
    meta["llm_mode"] = mode
    meta["ip_key"] = "" if keyed else key
    if mode != "live":
        _drop_manifest(vendor_id, meta)
    registry.write_meta(vendor_id, meta)


def _drop_manifest(vendor_id: str, meta: dict[str, Any]) -> None:
    folder = registry.vendor_dir(vendor_id)
    if folder is not None:
        (folder / "docs" / "manifest.json").unlink(missing_ok=True)
    for d in meta.get("documents", []):
        if d.get("status") == "read":
            d["status"], d["reason"] = "not_read", "Models are not available for this vendor now, so the scan was kept but not read"


# ---------- create ----------


def new_id() -> str:
    while True:
        vid = "U-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))
        if registry.vendor_dir(vid) is not None and not registry.vendor_dir(vid).exists():  # type: ignore[union-attr]
            return vid


def samples() -> list[str]:
    base = Path(settings.samples_dir)
    return [n for n in policy.STARTERS if (base / n / "sku_sheet.csv").is_file()]


def sample_dir(name: str) -> Path:
    if name not in samples():  # the name is matched against a fixed set, never joined into a path first
        raise UnknownSample(f"There is no sample called {name!r}", cause="Samples are beauty and electronics", fix="Pick a sample from the list")
    return Path(settings.samples_dir) / name


def _starter_policy(name: str) -> policy.Policy:
    if name not in policy.STARTERS:
        raise UploadError(f"Unknown starter playbook {name!r}", fix="Pick pet, beauty or electronics")
    return policy.starter(name).policy


def build_application(vid: str, app_in: ApplicationIn | None, pol: policy.Policy) -> tuple[dict[str, Any], bool]:
    """The stored application. Without one, a stub: every document the playbook requires is listed as pending
    verification with number "not provided" (so screening raises a warning, not a blocking failure) and the proposed
    terms stay empty. Returns (application, provided)."""
    provided = app_in is not None
    a = app_in or ApplicationIn(company_name="Uploaded vendor", brand_name="Uploaded vendor")
    vendor_types = pol.onboarding.vendor_types
    if a.vendor_type is not None and a.vendor_type not in vendor_types:
        raise UploadError(
            f"vendor_type {a.vendor_type!r} is not one of this playbook's vendor types",
            fix="Use one of: " + ", ".join(vendor_types),
        )
    docs = [d.model_dump() for d in a.documents]
    if not provided or not docs:
        listed = {d["type"] for d in docs}
        docs += [
            {"type": r.type, "number": "not provided", "valid_until": "", "status": "pending_verification"}
            for r in pol.screening.documents
            if r.type not in listed
        ]
    terms = a.proposed_terms.model_dump(exclude_none=True)
    return (
        {
            "vendor_id": vid,
            "company_name": a.company_name,
            "brand_name": a.brand_name,
            "contact_name": a.contact_name,
            "contact_email": a.contact_email,
            "city": a.city,
            **({"years_in_business": a.years_in_business} if a.years_in_business is not None else {}),
            "categories": a.categories,
            "vendor_type": a.vendor_type or next(iter(vendor_types), None),
            "documents": docs,
            "proposed_terms": terms,
            "pitch": a.pitch,
        },
        provided,
    )


def _copy_listings(source: Path, target: Path, vendor_id: str) -> None:
    """Competitor listings are keyed ``<vendor id>:<sku code>``. A stub file names its SKUs by code alone (a sandbox
    vendor's id does not exist until the upload), so each bare code is scoped to this vendor as it is copied."""
    with source.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    for row in rows[1:]:
        if row and ":" not in row[0]:
            row[0] = f"{vendor_id}:{row[0]}"
    with target.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)


def _copy_market(starter: str, dest: Path, vendor_id: str) -> bool:
    """Copy the starter's market stubs (benchmarks, search demand, catalog, competitor listings) into the vendor's own
    folder, filling the files a stub set may omit with empty ones. False when the starter ships none (the shared pet
    data is used)."""
    src = Path(settings.samples_dir) / starter / "market"
    if not (src / "category_benchmarks.json").is_file():
        return False
    for rel in registry.MARKET_FILES:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        source = src / rel
        if source.is_file() and rel.endswith("competitor_listings.csv"):
            _copy_listings(source, target, vendor_id)
        elif source.is_file():
            shutil.copyfile(source, target)
        elif rel.endswith("competitor_listings.csv"):
            target.write_text("vendor_sku_ref,marketplace,title,price,rating,review_count,est_monthly_sales\n", encoding="utf-8")
        elif rel.endswith("reviews.json"):
            target.write_text("{}", encoding="utf-8")
        elif rel.endswith("platform_catalog.csv"):
            target.write_text("sku_id,brand,name,category,subcategory,pack_size,mrp,selling_price,cost_price,margin_pct,monthly_units,rating,review_count,in_stock\n", encoding="utf-8")
        else:
            raise UploadError(f"Starter {starter!r} ships an incomplete market stub", cause=f"{rel} is missing")
    return True


class DocIn:
    def __init__(self, data: bytes, kind: str, title: str = "", declares: str = "") -> None:
        self.data, self.kind, self.title, self.declares = data, kind, uploads.clean(title)[:80], uploads.clean(declares)[:80]


def create(
    *,
    ip: str,
    keyed: bool,
    starter: str,
    sheet: bytes | None,
    sample: str | None,
    application: ApplicationIn | None,
    docs: list[DocIn],
) -> dict[str, Any]:
    """Validate everything, write the vendor into the registry atomically, and return its public description."""
    rate_check(ip)
    cleanup()
    if len(registry.ids()) >= settings.upload_max_active:
        raise SandboxFull()
    if len(docs) > settings.upload_max_docs:
        raise uploads.UploadTooLarge(f"At most {settings.upload_max_docs} documents", fix="Send the most important ones")
    if sample is not None:
        src = sample_dir(sample)
        starter = sample
        sheet = (src / "sku_sheet.csv").read_bytes()
        if application is None and not docs and (src / "application.json").is_file():
            application = uploads.parse_application_json((src / "application.json").read_bytes())
    pol = _starter_policy(starter)
    if sheet is None:
        raise UploadError("Upload a SKU sheet, or pick a sample", fix="CSV or XLSX, up to 200 rows")
    parsed = uploads.parse_sheet(sheet)
    vid = new_id()
    app_dict, provided = build_application(vid, application, pol)

    live = decide_llm_mode(keyed, ip_key(ip)) == "live"
    kinds = {k.kind: k for k in pol.documents.kinds}
    doc_meta: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    declared_types = {d["type"] for d in app_dict["documents"]}
    staged: list[tuple[str, bytes]] = []
    for n, d in enumerate(docs, start=1):
        info = uploads.validate_doc(d.data)
        if d.kind not in kinds:
            raise UploadError(f"Document {n}: {d.kind!r} is not a document kind of this playbook", fix="Pick one of: " + ", ".join(kinds) if kinds else "This playbook reads no documents")
        if kinds[d.kind].stage != "intake":
            raise UploadError(f"Document {n}: {kinds[d.kind].label} is read in the Catalog stage, which sandbox vendors do not run", fix="Upload intake documents such as licence certificates")
        if d.declares and d.declares not in declared_types:
            raise UploadError(f"Document {n}: it declares {d.declares!r}, which the application does not list")
        name = f"doc{n}.{info.ext}"
        staged.append((name, d.data))
        entry: dict[str, Any] = {"file": name, "name": name, "kind": d.kind, "title": d.title or kinds[d.kind].label, "declares": d.declares or None}
        if info.ext == "pdf":
            entry |= {"status": "not_read", "reason": "PDFs are stored but not rendered; upload the page as an image to have it read"}
        elif not pol.documents.enabled:
            entry |= {"status": "not_read", "reason": "This playbook does not read documents"}
        elif not live:
            entry |= {"status": "not_read", "reason": "Rules-only: no model reads scans" if settings.model_mode != "mock" else "Mock mode: scans are stored, not read"}
        else:
            entry |= {"status": "read", "reason": None}
            manifest.append({"file": name, "kind": d.kind, "title": entry["title"], "pages": [name], **({"declares": d.declares} if d.declares else {})})
        doc_meta.append(entry)

    root = registry.root()
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".tmp-{vid}"
    final = registry.vendor_dir(vid)
    assert final is not None
    try:
        tmp.mkdir()
        (tmp / "sku_sheet.csv").write_bytes(uploads.sheet_to_csv(parsed))
        (tmp / "application.json").write_text(json.dumps(app_dict, indent=2), encoding="utf-8")
        (tmp / "docs").mkdir()
        for name, data in staged:
            (tmp / "docs" / name).write_bytes(data)
        if manifest:
            (tmp / "docs" / "manifest.json").write_text(json.dumps({"documents": manifest}), encoding="utf-8")
        has_market = _copy_market(starter, tmp / "data", vid)
        now = time.time()
        meta = {
            "id": vid,
            "starter": starter,
            "llm_mode": decide_llm_mode(keyed, ip_key(ip)),
            "ip_key": "" if keyed else ip_key(ip),
            "created_at": now,
            "expires_at": now + settings.upload_ttl_hours * 3600,
            "source": f"sample:{sample}" if sample else "upload",
            "application_provided": provided,
            "market_stubs": has_market,
            "sku_count": len(parsed.rows),
            "warnings": parsed.warnings,
            "documents": doc_meta,
        }
        (tmp / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        tmp.rename(final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    try:
        _smoke(vid)
    except CategoryOSError:
        registry.remove(vid)
        raise
    except Exception as exc:
        registry.remove(vid)
        log.exception("sandbox vendor %s failed its first run of the engine", vid)
        raise UploadError("The engine could not read this sheet", cause=type(exc).__name__ + ": " + str(exc)[:200], fix="Check prices are numbers and codes are filled") from exc
    persist.notify()  # on Modal the new files reach the Volume
    return public(vid)


def _smoke(vid: str) -> None:
    from app.metrics import apply_levers, build_base

    apply_levers(build_base(vid))


# ---------- read ----------


def public(vid: str) -> dict[str, Any]:
    meta = registry.read_meta(vid)
    assert meta is not None
    now = time.time()
    return {
        "id": vid,
        "starter": meta["starter"],
        "starter_label": STARTER_LABELS.get(meta["starter"], meta["starter"]),
        "llm_mode": meta["llm_mode"],
        "mode_label": MODE_LABELS.get(meta["llm_mode"], meta["llm_mode"]),
        "source": meta.get("source", "upload"),
        "created_at": meta["created_at"],
        "expires_at": meta["expires_at"],
        "ttl_remaining_s": max(int(meta["expires_at"] - now), 0),
        "application_provided": meta.get("application_provided", False),
        "market_stubs": meta.get("market_stubs", False),
        "sku_count": meta.get("sku_count", 0),
        "warnings": meta.get("warnings", []),
        "documents": [{k: v for k, v in d.items() if k != "file"} for d in meta.get("documents", [])],
        "url": f"/vendors/{vid}",
    }


def options(keyed: bool, ip: str) -> dict[str, Any]:
    """What /try shows: starters (with their vendor types and document kinds), limits, and the model mode a new upload gets."""
    out = []
    for name in policy.STARTERS:
        pol = policy.starter(name).policy
        out.append(
            {
                "id": name,
                "label": STARTER_LABELS[name],
                "vertical": pol.business.vertical,
                "vendor_types": {k: v.label for k, v in pol.onboarding.vendor_types.items()},
                "required_documents": [r.type for r in pol.screening.documents],
                "document_kinds": [{"kind": k.kind, "label": k.label} for k in pol.documents.kinds if k.stage == "intake"] if pol.documents.enabled else [],
                "has_sample": name in samples(),
                "has_market_data": name == "pet" or (Path(settings.samples_dir) / name / "market" / "category_benchmarks.json").is_file(),
            }
        )
    mode = decide_llm_mode(keyed, ip_key(ip))
    return {
        "starters": out,
        "limits": {
            "sheet_mb": settings.upload_max_sheet_bytes / 1024 / 1024,
            "rows": settings.upload_max_rows,
            "documents": settings.upload_max_docs,
            "document_mb": settings.upload_max_doc_bytes / 1024 / 1024,
            "ttl_hours": settings.upload_ttl_hours,
        },
        "llm_mode": mode,
        "mode_label": MODE_LABELS[mode],
        "live_budget_usd": settings.upload_live_budget_usd_per_ip,
    }


# ---------- cleanup ----------


def cleanup(now: float | None = None) -> list[str]:
    """Delete expired sandbox vendors (and abandoned half-written folders). Returns the ids removed."""
    now = now if now is not None else time.time()
    removed: list[str] = []
    for vid in registry.ids():
        meta = registry.read_meta(vid)
        folder = registry.vendor_dir(vid)
        if meta is None:
            if folder is not None and now - folder.stat().st_mtime > 3600:
                registry.remove(vid)
                removed.append(vid)
        elif registry.is_expired(meta, now):
            registry.remove(vid)
            removed.append(vid)
    base = registry.root()
    if base.is_dir():
        for p in base.glob(".tmp-*"):
            if now - p.stat().st_mtime > 3600:
                shutil.rmtree(p, ignore_errors=True)
    if removed:
        _forget()
    return removed


def _forget() -> None:
    """Drop cached parses of deleted vendors."""
    from app import data_loader, metrics

    metrics.build_base.cache_clear()  # type: ignore[attr-defined]
    data_loader._csv_rows.cache_clear()
    data_loader._json.cache_clear()


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(max(settings.upload_cleanup_interval_min, 0.1) * 60)
        try:
            removed = await asyncio.to_thread(cleanup)
            if removed:
                log.info("sandbox cleanup removed %d expired vendor(s)", len(removed))
        except Exception:
            log.exception("sandbox cleanup failed")


# ---------- ASGI middleware ----------

_PATH = re.compile(r"^/api/(?:vendors|docs|assets)/(U-[a-z0-9]{8})(?:/|$)")


class SandboxScopeMiddleware:
    """Puts the request in a sandbox vendor's scope (its playbook, market data and model mode) when the path names one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope_: Scope, receive: Receive, send: Send) -> None:
        match = _PATH.match(scope_.get("path", "")) if scope_["type"] == "http" else None
        sc = registry.scope_for(match.group(1)) if match else None
        if sc is None:
            await self.app(scope_, receive, send)
            return
        with scope.use(sc):
            await self.app(scope_, receive, send)
