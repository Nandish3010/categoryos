import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.data_loader import load_benchmarks, load_catalog

_CAT = re.compile(r"\bcats?\b|\bkittens?\b|catnip|hairball|feline")
_DOG = re.compile(r"\bdogs?\b|\bpupp(?:y|ies)\b|canine")

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cat litter", re.compile(r"litter")),
    ("grooming", re.compile(r"shampoo|conditioner|ear (?:cleaner|drops)|balm|serum|brush|clipper|grooming")),
    ("treats", re.compile(r"treat|chew|bites?\b|biscuit|sticks?\b|jerky|strips?\b|dental")),
    ("toys", re.compile(r"\btoys?\b|\btug\b|teaser|wand|catnip|plush|squeak|\bball\b")),
    ("accessories", re.compile(r"collar|harness|leash|bowl|scratch")),
    ("wet", re.compile(r"\bwet\b|pouch|gravy|pate|stew|\btray\b|chunks|mousse|jelly")),
    ("dry", re.compile(r"kibble|\bdry\b|adult|puppy|kitten|senior|large breed|\bfood\b")),
    ("supplement", re.compile(r"probiotic|vitamin|supplement|powder|drops|joint")),
)


@dataclass(frozen=True)
class Classification:
    category: str
    subcategory: str
    flags: tuple[str, ...] = field(default_factory=tuple)


@lru_cache(maxsize=1)
def catalog_subcategories() -> dict[str, frozenset[str]]:
    subs: dict[str, set[str]] = {}
    for sku in load_catalog():
        subs.setdefault(sku.category, set()).add(sku.subcategory)
    return {k: frozenset(v) for k, v in subs.items()}


def categories() -> tuple[str, ...]:
    return tuple(load_benchmarks())


def species(text: str, hint: str = "dog") -> str:
    cats, dogs = len(_CAT.findall(text)), len(_DOG.findall(text))
    if cats == dogs:
        return hint
    return "cat" if cats > dogs else "dog"


def _first_rule(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for priority, (key, pattern) in enumerate(_RULES):
        if pattern.search(text) and (best is None or priority < best[0]):
            best = (priority, key)
    return best[1] if best else None


def _subcategory(category: str, text: str, kind: str) -> str:
    if category == "cat litter":
        if "tofu" in text:
            return "tofu"
        if "silica" in text or "crystal" in text:
            return "crystal"
        return "clumping"
    if category == "grooming":
        if "shampoo" in text:
            return "shampoo"
        if re.search(r"brush|clipper", text):
            return "tools"
        return "hygiene"
    if category == "treats":
        if re.search(r"dental|tartar", text):
            return "dental"
        return "cat treats" if kind == "cat" else "dog treats"
    if category == "toys":
        return "cat toys" if kind == "cat" else "dog toys"
    if category == "accessories":
        for word, sub in (("collar", "collars"), ("harness", "harness"), ("leash", "leashes"), ("bowl", "bowls")):
            if word in text:
                return sub
        return "furniture"
    if category.endswith("wet food"):
        for word, sub in (("pate", "pate"), ("mousse", "mousse"), ("jelly", "jelly"), ("chunk", "chunks")):
            if word in text:
                return sub
        return "gravy"
    if "kitten" in text:
        return "kitten"
    if "puppy" in text:
        return "puppy"
    if "senior" in text:
        return "senior"
    return "adult"


def classify(name: str, description: str = "", hint: str = "dog") -> Classification:
    flags: list[str] = []
    name_l, desc_l = name.lower(), (description or "").lower()
    rule = _first_rule(name_l)
    text = name_l
    if rule is None:
        rule = _first_rule(desc_l)
        text = f"{name_l} {desc_l}"
    if rule is None:
        rule, text = "supplement", f"{name_l} {desc_l}"
        flags.append("unclassified")
    kind = species(name_l, species(desc_l, hint)) if rule in {"wet", "dry", "treats", "toys"} else hint
    if rule == "supplement":
        category, flags = "treats", flags + ["approx_category"]
        sub = "cat treats" if kind == "cat" else "dog treats"
    elif rule in {"wet", "dry"}:
        category = f"{kind} {rule} food"
        sub = _subcategory(category, text, kind)
    else:
        category = rule
        sub = _subcategory(category, text, kind)
    if category not in categories():
        flags.append("unclassified")
        category = categories()[0]
    if sub not in catalog_subcategories().get(category, frozenset()):
        flags.append("subcategory_not_in_catalog")
    return Classification(category, sub, tuple(dict.fromkeys(flags)))
