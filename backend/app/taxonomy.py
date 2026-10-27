"""SKU classification driven entirely by the playbook's ``taxonomy`` section: ordered category rules, optional segments
(pet species, gender, skin type...), subcategory patterns and a fallback. No vertical is hardcoded here."""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app import policy
from app.data_loader import load_catalog


@dataclass(frozen=True)
class Classification:
    category: str
    subcategory: str
    flags: tuple[str, ...] = field(default_factory=tuple)


@lru_cache(maxsize=256)
def _rx(patterns: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(patterns), re.IGNORECASE)


@lru_cache(maxsize=1)
def _catalog_subcategories() -> dict[str, frozenset[str]]:
    subs: dict[str, set[str]] = {}
    for sku in load_catalog():
        subs.setdefault(sku.category, set()).add(sku.subcategory)
    return {k: frozenset(v) for k, v in subs.items()}


def catalog_subcategories() -> dict[str, frozenset[str]]:
    return _catalog_subcategories()


def categories() -> tuple[str, ...]:
    return policy.category_names()


def segment_value(segment: policy.Segment, text: str, hint: str | None = None) -> str:
    """The segment value with most pattern matches in ``text``; ties go to ``hint``, then the first value."""
    counts = {v: len(_rx(tuple(p)).findall(text)) if p else 0 for v, p in segment.values.items()}
    best = max(counts.values())
    leaders = [v for v, c in counts.items() if c == best]
    if hint in leaders:
        return hint
    return leaders[0]


def segment_hints(text: str) -> dict[str, str]:
    """Vendor-level segment values (for example the species a vendor mostly sells), used when a SKU's own text is silent."""
    return {s.name: segment_value(s, text.lower()) for s in policy.get().taxonomy.segments}


def segments_for(text: str, hints: dict[str, str] | None = None) -> dict[str, str]:
    """Segment values for a piece of text with the playbook's default when the text is silent."""
    hints = hints or {}
    return {s.name: segment_value(s, text.lower(), hints.get(s.name)) for s in policy.get().taxonomy.segments}


def _first_rule(text: str, rules: list[policy.TaxCategory]) -> policy.TaxCategory | None:
    for rule in rules:
        if rule.patterns and _rx(tuple(rule.patterns)).search(text):
            return rule
    return None


def _sub_name(rule: policy.TaxCategory, text: str, values: dict[str, str]) -> str:
    default = None
    for sub, pats in rule.subcategories.items():
        if not pats:
            default = default or sub
        elif _rx(tuple(pats)).search(text):
            return sub.format_map(_Safe(values))
    if default:
        return default.format_map(_Safe(values))
    return next(iter(rule.subcategories), "general")


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def classify(name: str, description: str = "", hint: dict[str, str] | None = None) -> Classification:
    tax = policy.get().taxonomy
    hint = hint or {}
    flags: list[str] = []
    name_l, desc_l = name.lower(), (description or "").lower()
    rule = _first_rule(name_l, tax.categories)
    text = name_l
    if rule is None:
        rule = _first_rule(desc_l, tax.categories)
        text = f"{name_l} {desc_l}"
    approximate = rule is None or rule.approximate_as is not None
    if rule is None:
        flags.append("unclassified")
        text = f"{name_l} {desc_l}"
    target_name = tax.fallback_category if rule is None else (rule.approximate_as or rule.name)
    # Segments come from the SKU's own text, except for approximate/unclassified rows, which follow the vendor-level hint.
    values = dict(hint) if approximate else {
        s.name: segment_value(s, name_l, segment_value(s, desc_l, hint.get(s.name))) for s in tax.segments
    }
    for s in tax.segments:
        values.setdefault(s.name, next(iter(s.values)))
    category = target_name.format_map(_Safe(values))
    owner = next((r for r in tax.categories if r.name == target_name), None)
    sub = _sub_name(owner, "" if approximate else text, values) if owner else "general"
    if approximate:
        flags.append("approx_category")
    if category not in categories():
        flags.append("unclassified")
        category = tax.fallback_category
    if sub not in catalog_subcategories().get(category, frozenset()):
        flags.append("subcategory_not_in_catalog")
    return Classification(category, sub, tuple(dict.fromkeys(flags)))
