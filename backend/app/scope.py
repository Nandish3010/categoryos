"""Request/run scope for sandbox (bring-your-own) vendors. Dependency-free so any module can import it.

``use(scope)`` marks the current context as working on one vendor; policy, data_loader, llm and ledger read it to
pick that vendor's playbook, its market data, its forced model mode and its per-IP spend bucket. The built-in vendors
V001 to V004 never set anything, so their behaviour is unchanged."""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    vendor_id: str
    starter: str  # starter playbook name: pet | beauty | electronics
    llm_mode: str  # rules_only | mock | live
    ip_key: str  # hashed client address: the per-IP budget bucket
    market_dir: str | None = None  # the vendor's own market stubs, when its starter ships them


_current: contextvars.ContextVar[Scope | None] = contextvars.ContextVar("categoryos_scope", default=None)


def current() -> Scope | None:
    return _current.get()


@contextmanager
def use(scope: Scope | None) -> Iterator[None]:
    token = _current.set(scope)
    try:
        yield
    finally:
        _current.reset(token)
