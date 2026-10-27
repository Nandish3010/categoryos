"""Deterministic reading of delivery dates in vendor email phrases. The verifier uses this to check the ETA the model
extracted; it is deliberately conservative (the later end of a range) and returns None for vague promises."""

import re
from datetime import date, timedelta

_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DAY_MON = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?{_MON}\b", re.IGNORECASE)
_MON_DAY = re.compile(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_IN_DAYS = re.compile(r"\b(\d{1,2})(?:\s*(?:-|to)\s*(\d{1,2}))?\s*(working|business)?\s*days?\b", re.IGNORECASE)
_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "thurs": 3, "friday": 4, "saturday": 5, "sunday": 6}
_WEEKDAY = re.compile(r"\b(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE)


def add_business_days(start: date, n: int) -> date:
    day = start
    while n > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day


def _year_for(month: int, day: int, received: date) -> date | None:
    try:
        candidate = date(received.year, month, day)
    except ValueError:
        return None
    if candidate < received - timedelta(days=60):
        candidate = date(received.year + 1, month, day)
    return candidate


def resolve_eta(text: str, received: date) -> date | None:
    """The latest delivery date the phrase promises, or None when it promises no date ("shortly", "next week")."""
    found: list[date] = []
    low = text.lower()
    for m in _DAY_MON.finditer(text):
        d = _year_for(_MONTHS[m.group(2)[:3].lower()], int(m.group(1)), received)
        if d:
            found.append(d)
    for m in _MON_DAY.finditer(text):
        d = _year_for(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), received)
        if d:
            found.append(d)
    for m in _SLASH.finditer(text):
        d = _year_for(int(m.group(2)), int(m.group(1)), received) if 1 <= int(m.group(2)) <= 12 else None
        if d:
            found.append(d)
    for m in _IN_DAYS.finditer(text):
        n = int(m.group(2) or m.group(1))
        found.append(add_business_days(received, n) if m.group(3) else received + timedelta(days=n))
    for m in _WEEKDAY.finditer(text):
        target = _WEEKDAYS[m.group(1).lower()]
        ahead = (target - received.weekday()) % 7 or 7
        found.append(received + timedelta(days=ahead))
    if re.search(r"\btomorrow\b", low):
        found.append(received + timedelta(days=1))
    if not found:
        return None
    return max(found)
