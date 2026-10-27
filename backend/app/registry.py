"""Sandbox vendor registry: where an uploaded vendor lives on disk, whether it still exists, and which scope it runs in.

Layout (all under ``settings.state_dir``, never in the repo; a Volume path on Modal)::

    vendors/U-abc12345/
        meta.json          created_at, expires_at, starter playbook, model mode, counts, warnings
        sku_sheet.csv      the parsed sheet, re-serialised by us (the uploaded bytes and file name are never stored)
        application.json   validated application
        docs/              uploaded images, stored under names we generate (doc1.png ...), plus manifest.json when read
        data/              the vendor's own market stubs (category_benchmarks.json, platform_catalog.csv, market/...)

A vendor past its TTL is treated as not existing (the cleanup job deletes it later). This module imports nothing from
the rest of the app except config and constants, so data_loader can use it."""

import json
import re
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app import scope
from app.config import settings
from app.constants import VENDOR_ID_PATTERN

_VALID = re.compile(rf"^(?:{VENDOR_ID_PATTERN})$")
_SANDBOX = re.compile(r"^U-[a-z0-9]{8}$")

# The files a sandbox vendor may serve to the verifier and the UI, by name relative to its folder.
VENDOR_FILES = ("sku_sheet.csv", "application.json", "call_transcript.json")
MARKET_FILES = (
    "category_benchmarks.json",
    "platform_catalog.csv",
    "market/competitor_listings.csv",
    "market/search_demand.csv",
    "market/reviews.json",
)


def is_valid_id(vendor_id: str) -> bool:
    return bool(_VALID.match(vendor_id))


def is_sandbox_id(vendor_id: str | None) -> bool:
    return bool(vendor_id) and bool(_SANDBOX.match(vendor_id or ""))


def root() -> Path:
    return Path(settings.state_dir) / "vendors"


def vendor_dir(vendor_id: str) -> Path | None:
    """The vendor's folder when the id is a well-formed sandbox id and resolves inside the registry root. No existence check."""
    if not is_sandbox_id(vendor_id):
        return None
    base = root().resolve()
    path = (base / vendor_id).resolve()
    return path if path.parent == base else None


def read_meta(vendor_id: str) -> dict[str, Any] | None:
    path = vendor_dir(vendor_id)
    if path is None:
        return None
    try:
        data = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_meta(vendor_id: str, meta: dict[str, Any]) -> None:
    path = vendor_dir(vendor_id)
    assert path is not None
    tmp = path / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path / "meta.json")


def is_expired(meta: dict[str, Any], now: float | None = None) -> bool:
    return (now if now is not None else time.time()) >= float(meta.get("expires_at", 0))


def exists(vendor_id: str) -> bool:
    """A live (present, not expired) sandbox vendor."""
    meta = read_meta(vendor_id)
    return meta is not None and not is_expired(meta)


def ids() -> list[str]:
    """Every sandbox folder on disk (expired or not), oldest first."""
    base = root()
    if not base.is_dir():
        return []
    found = [p for p in base.iterdir() if p.is_dir() and is_sandbox_id(p.name)]
    return [p.name for p in sorted(found, key=lambda p: p.stat().st_mtime)]


def remove(vendor_id: str) -> bool:
    path = vendor_dir(vendor_id)
    if path is None or not path.exists():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def scope_for(vendor_id: str) -> scope.Scope | None:
    """The run scope of a live sandbox vendor, None for the built-in vendors and for unknown or expired ids."""
    meta = read_meta(vendor_id)
    if meta is None or is_expired(meta):
        return None
    path = vendor_dir(vendor_id)
    assert path is not None
    market = path / "data"
    return scope.Scope(
        vendor_id=vendor_id,
        starter=str(meta.get("starter", "pet")),
        llm_mode=str(meta.get("llm_mode", "rules_only")),
        ip_key=str(meta.get("ip_key", "")),
        market_dir=str(market) if (market / "category_benchmarks.json").exists() else None,
        public=bool(meta.get("public_live", False)) and bool(meta.get("ip_key")),
    )


@contextmanager
def scoped(vendor_id: str) -> Iterator[None]:
    """Enter the vendor's scope (playbook, market data, model mode, spend bucket). A no-op for the built-in vendors, and
    when this vendor's scope is already active."""
    if not is_sandbox_id(vendor_id):
        yield
        return
    wanted = scope_for(vendor_id)  # re-read each time: the model mode can change between a request and its run
    if scope.current() == wanted:
        yield
        return
    with scope.use(wanted):
        yield


def resolve_data_file(rel: str) -> Path:
    """Where a verifier-style relative path (``vendors/U-x/sku_sheet.csv``, ``market/search_demand.csv``) is read from."""
    parts = rel.split("/")
    if any(p in ("", ".", "..") or "\\" in p for p in parts):
        raise ValueError(f"not a plain relative path: {rel!r}")
    if len(parts) >= 3 and parts[0] == "vendors" and is_sandbox_id(parts[1]):
        folder = vendor_dir(parts[1])
        if folder is not None:
            return folder.joinpath(*parts[2:])
    sc = scope.current()
    if sc is not None and sc.market_dir and rel in MARKET_FILES:
        return Path(sc.market_dir) / rel
    return Path(settings.data_dir) / rel
