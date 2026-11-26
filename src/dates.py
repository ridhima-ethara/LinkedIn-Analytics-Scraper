"""Date-window resolution, parsing and verification.

LinkedIn's admin analytics offers rolling presets ("Past 28 days") plus a custom
start/end range. A calendar-year request such as 2026 must therefore be driven
through the custom picker, and the window LinkedIn ends up displaying has to be
read back and compared against what was asked for — so the reports can never
claim a range that was not actually applied.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# Accepted input formats for config/CLI values and for on-page date text.
_INPUT_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y",
                  "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
                  "%d %b %Y", "%d %B %Y", "%Y/%m/%d")

_MDY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_MONTH_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:,)?\s*(\d{4})?\b",
    re.I)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# LinkedIn's longest supported Page-analytics window (12 months).
MAX_WINDOW_DAYS = 365


class DateWindowError(ValueError):
    pass


def parse_date(text: Optional[str]) -> Optional[date]:
    """Parse a single date from config input or on-page text."""
    if not text:
        return None
    s = str(text).strip().strip(",")
    if not s:
        return None
    for fmt in _INPUT_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = _MDY_RE.search(s)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = _MONTH_RE.search(s)
    if m:
        try:
            year = int(m.group(3)) if m.group(3) else date.today().year
            return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {year}",
                                     "%b %d %Y").date()
        except ValueError:
            return None
    return None


def extract_dates(label: Optional[str]) -> List[date]:
    """Every date mentioned in an on-page range label, in order."""
    out: List[date] = []
    if not label:
        return out
    for m in _MDY_RE.finditer(label):
        d = parse_date(m.group(0))
        if d:
            out.append(d)
    if not out:
        years = _YEAR_RE.findall(label)
        for i, m in enumerate(_MONTH_RE.finditer(label)):
            year = m.group(3) or (years[-1] if years else None)
            if not year:
                continue
            d = parse_date(f"{m.group(1)} {m.group(2)} {year}")
            if d:
                out.append(d)
    return out


def resolve_window(extraction: Dict[str, Any], today: Optional[date] = None
                   ) -> Optional[Tuple[date, date]]:
    """Resolve `extraction` config into an explicit (start, end) window.

    Returns None for rolling presets / keep_default, which need no window.
    Accepted forms:
        date_range: custom      + custom_start / custom_end
        date_range: year_2026   (or custom_year: 2026)
        date_range: "2026-01-01..2026-11-25"
    An end date in the future is clamped to today, because LinkedIn cannot
    report on days that have not happened.
    """
    today = today or date.today()
    raw = str(extraction.get("date_range", "")).strip()

    start: Optional[date] = None
    end: Optional[date] = None

    m = re.fullmatch(r"(.+?)\s*\.\.\s*(.+)", raw)
    if m:
        start, end = parse_date(m.group(1)), parse_date(m.group(2))
        if not start or not end:
            raise DateWindowError(f"could not parse date_range {raw!r}; use YYYY-MM-DD..YYYY-MM-DD")
    else:
        year_token = None
        ym = re.fullmatch(r"(?:year_|calendar_year_|cy)(20\d{2})", raw, re.I)
        if ym:
            year_token = int(ym.group(1))
        elif extraction.get("custom_year"):
            year_token = int(extraction["custom_year"])
        if year_token:
            start, end = date(year_token, 1, 1), date(year_token, 12, 31)
        elif raw == "custom":
            start = parse_date(extraction.get("custom_start"))
            end = parse_date(extraction.get("custom_end")) or today
            if not start:
                raise DateWindowError(
                    "date_range: custom requires extraction.custom_start "
                    "(YYYY-MM-DD), or use --start/--end")
        else:
            return None  # rolling preset or keep_default

    assert start is not None and end is not None
    if end > today:
        end = today
    if start > end:
        raise DateWindowError(f"start {start} is after end {end}")
    return start, end


def window_label(window: Tuple[date, date]) -> str:
    return f"{window[0].isoformat()} .. {window[1].isoformat()}"


def window_days(window: Tuple[date, date]) -> int:
    return (window[1] - window[0]).days + 1


def nearest_preset(window: Tuple[date, date], today: Optional[date] = None) -> str:
    """Closest rolling preset to a custom window, for fallback purposes."""
    days = window_days(window)
    for preset, span in (("past_7_days", 7), ("past_28_days", 28),
                         ("past_90_days", 90), ("past_365_days", 365)):
        if days <= span:
            return preset
    return "past_365_days"


def verify_applied(shown_label: str, window: Tuple[date, date],
                   tolerance_days: int = 2) -> Tuple[bool, str]:
    """Did LinkedIn actually apply the window we asked for?

    Compares the range label LinkedIn displays against the requested window.
    Returns (verified, explanation) — the explanation goes into the report
    whether or not it matched.
    """
    start, end = window
    dates = extract_dates(shown_label)
    if len(dates) >= 2:
        got_start, got_end = dates[0], dates[-1]
        ds = abs((got_start - start).days)
        de = abs((got_end - end).days)
        if ds <= tolerance_days and de <= tolerance_days:
            return True, (f"LinkedIn displays {got_start} .. {got_end}, matching the "
                          f"requested {start} .. {end} (within {tolerance_days} day(s)).")
        return False, (f"LinkedIn displays {got_start} .. {got_end}, which does NOT match "
                       f"the requested {start} .. {end} (off by {ds}/{de} day(s)). "
                       f"Values are reported for the displayed range.")
    years = {int(y) for y in _YEAR_RE.findall(shown_label or "")}
    if years and years <= {start.year, end.year}:
        return False, (f"LinkedIn's range label {shown_label!r} shows only year(s) "
                       f"{sorted(years)} and no explicit start/end dates, so the exact "
                       f"window could not be confirmed.")
    return False, (f"Could not read an explicit date range from LinkedIn's label "
                   f"{shown_label!r}; the applied window is unconfirmed.")


def in_window(value: Optional[str], window: Optional[Tuple[date, date]]) -> Optional[bool]:
    """Is a post's date inside the window? None when the date is unparseable."""
    if not window:
        return True
    d = parse_date(value)
    if not d:
        return None
    return window[0] <= d <= window[1]
