"""Python-side wrappers around the in-page helpers, plus value parsing,
page-settling, pagination and retry utilities.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar

from playwright.sync_api import Error as PwError
from playwright.sync_api import Page, TimeoutError as PwTimeout

from .jsfuncs import INSTALL_JS
from .logging_setup import get_logger

log = get_logger("dom")

T = TypeVar("T")

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000,
           "bn": 1_000_000_000, "mn": 1_000_000}

_LOGIN_URL_RE = re.compile(
    r"/(login|uas/login|authwall|checkpoint/challenge|checkpoint/lg)", re.I
)


class SessionExpired(RuntimeError):
    """The authenticated session is gone (login wall / checkpoint)."""


class SectionUnavailable(RuntimeError):
    """A section could not be opened at all (404 / permission wall)."""

    def __init__(self, message: str, limitation: str) -> None:
        super().__init__(message)
        self.limitation = limitation


# --------------------------------------------------------------------------
# value parsing
# --------------------------------------------------------------------------
def parse_number(raw: Optional[str]) -> Optional[float | int]:
    """'1,234' -> 1234 | '1.2K' -> 1200 | '3.45%' -> 3.45 | '' -> None.

    Returns None when nothing numeric is present; the caller then keeps the
    metric as not-extracted rather than inventing a value.
    """
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", " ")
    if not s:
        return None
    s = s.replace("’", "").replace("'", "").replace(" ", "")
    m = re.match(r"^([+-]?[\d.,]+)\s*(%|k|m|b|bn|mn)?$", s, re.I)
    if not m:
        m = re.search(r"([+-]?[\d.,]+)\s*(%|k|m|b|bn|mn)?", s, re.I)
    if not m:
        return None
    num, suffix = m.group(1), (m.group(2) or "").lower()
    # 1,234 -> 1234 ; 1,2 (unlikely in en-US) -> 1.2
    if "," in num and "." in num:
        num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", "") if re.search(r",\d{3}(\D|$)", num + " ") else num.replace(",", ".")
    try:
        value: float = float(num)
    except ValueError:
        return None
    if suffix in _SUFFIX:
        value *= _SUFFIX[suffix]
    if suffix == "%":
        return round(value, 4)
    return int(value) if value.is_integer() else round(value, 4)


def unit_for(raw: Optional[str]) -> str:
    if raw and "%" in str(raw):
        return "percent"
    return "count"


# --------------------------------------------------------------------------
# helper invocation
# --------------------------------------------------------------------------
def ensure_helpers(page: Page) -> None:
    try:
        if not page.evaluate("() => !!window.__lia"):
            page.evaluate(INSTALL_JS)
    except PwError:
        page.evaluate(INSTALL_JS)


def _call(page: Page, expr: str, arg: Any = None, default: Any = None) -> Any:
    try:
        ensure_helpers(page)
        return page.evaluate(expr, arg)
    except (PwError, PwTimeout) as exc:
        log.debug("js call failed (%s): %s", expr[:40], exc)
        return default


def find_metric(page: Page, labels: Sequence[str], mode: str = "number",
                allow_percent: bool = False) -> Optional[Dict[str, Any]]:
    return _call(
        page,
        "(a) => window.__lia.findMetric(a.labels, a.mode, a.pct)",
        {"labels": list(labels), "mode": mode, "pct": bool(allow_percent)},
    )


def click_date_control(page: Page) -> str:
    """Open the date-range control; returns how it was found ('' = not found)."""
    return str(_call(page, "() => window.__lia.clickDateControl()", default="") or "")


def click_own_text(page: Page, pattern: str) -> bool:
    """Click an element whose own text matches `pattern` (in-page JS click)."""
    return bool(_call(page, "(p) => window.__lia.clickOwnText(p)", pattern, default=False))


def list_after_heading(page: Page, heading_pattern: str,
                       max_items: int = 25) -> Optional[Dict[str, Any]]:
    """Items listed under a heading, for lists LinkedIn renders without values."""
    return _call(page, "(a) => window.__lia.listAfterHeading(a.p, a.n)",
                 {"p": heading_pattern, "n": max_items})


def tables(page: Page) -> List[Dict[str, Any]]:
    return _call(page, "() => window.__lia.tables()", default=[]) or []


def breakdown(page: Page, scope: str = "") -> Optional[Dict[str, Any]]:
    return _call(page, "(s) => window.__lia.breakdown(s)", scope)


def nav_links(page: Page) -> List[Dict[str, str]]:
    return _call(page, "() => window.__lia.navLinks()", default=[]) or []


def empty_states(page: Page) -> List[str]:
    return _call(page, "() => window.__lia.emptyStates()", default=[]) or []


def access_walls(page: Page) -> List[str]:
    return _call(page, "() => window.__lia.accessWalls()", default=[]) or []


def clickables(page: Page, pattern: str) -> List[Dict[str, str]]:
    return _call(page, "(p) => window.__lia.clickables(p)", pattern, default=[]) or []


def date_range_labels(page: Page) -> List[str]:
    return _call(page, "() => window.__lia.dateRangeLabel()", default=[]) or []


def page_text(page: Page) -> str:
    return _call(page, "() => window.__lia.rawText()", default="") or ""


def post_urns(page: Page) -> List[str]:
    return _call(page, "() => window.__lia.postUrns()", default=[]) or []


# --------------------------------------------------------------------------
# navigation / settling
# --------------------------------------------------------------------------
def goto(page: Page, url: str, *, timeout_ms: int = 60000, settle_ms: int = 2500,
         scroll_passes: int = 6) -> None:
    """Navigate and wait until charts/tables have hydrated."""
    log.info("navigate -> %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    guard_session(page)
    settle(page, settle_ms=settle_ms, scroll_passes=scroll_passes)


def settle(page: Page, *, settle_ms: int = 2500, scroll_passes: int = 6) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PwTimeout:
        log.debug("networkidle timed out; continuing")
    page.wait_for_timeout(settle_ms)
    for _ in range(max(0, scroll_passes)):
        try:
            page.evaluate("() => window.scrollBy(0, Math.round(window.innerHeight * 0.85))")
        except PwError:
            break
        page.wait_for_timeout(450)
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except PwError:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PwTimeout:
        pass
    page.wait_for_timeout(600)
    ensure_helpers(page)


def guard_session(page: Page) -> None:
    """Raise SessionExpired if LinkedIn bounced us to a login/checkpoint page."""
    url = page.url or ""
    if _LOGIN_URL_RE.search(url):
        raise SessionExpired(f"redirected to an authentication page: {url}")
    try:
        title = (page.title() or "").lower()
    except PwError:
        title = ""
    if "sign in" in title or "log in" in title or title.startswith("linkedin login"):
        raise SessionExpired(f"authentication page title: {title!r} at {url}")


def expand_all(page: Page, rounds: int = 8,
               pattern: str = r"^(show|load|see) more|^show \d+ more|more results") -> int:
    """Click every 'Show more' / 'Load more' control until exhausted."""
    clicks = 0
    for _ in range(max(0, rounds)):
        try:
            btn = page.locator(
                "button:visible, a[role='button']:visible"
            ).filter(has_text=re.compile(pattern, re.I)).first
            if btn.count() == 0:
                break
            btn.scroll_into_view_if_needed(timeout=5000)
            btn.click(timeout=8000)
            clicks += 1
            page.wait_for_timeout(1800)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PwTimeout:
                pass
        except (PwError, PwTimeout) as exc:
            log.debug("no further 'show more' control: %s", str(exc).splitlines()[0])
            break
    if clicks:
        log.info("expanded paginated content with %d click(s)", clicks)
    return clicks


def click_text(page: Page, pattern: str, *, timeout_ms: int = 8000,
               role_hint: str = "") -> bool:
    """Click the first visible control whose text matches `pattern`."""
    rx = re.compile(pattern, re.I)
    selectors = [
        "button:visible", "[role='tab']:visible", "[role='menuitem']:visible",
        "[role='option']:visible", "a[role='button']:visible", "label:visible",
        "a[href]:visible", "li:visible",
    ]
    if role_hint:
        selectors.insert(0, f"{role_hint}:visible")
    for sel in selectors:
        try:
            loc = page.locator(sel).filter(has_text=rx).first
            if loc.count() == 0:
                continue
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=timeout_ms)
            page.wait_for_timeout(1500)
            return True
        except (PwError, PwTimeout):
            continue
    return False


def screenshot(page: Page, path: Path, full_page: bool = True) -> Optional[str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=full_page)
        log.info("screenshot -> %s", path)
        return str(path)
    except (PwError, PwTimeout) as exc:
        log.warning("screenshot failed: %s", exc)
        return None


# --------------------------------------------------------------------------
# retry
# --------------------------------------------------------------------------
def with_retries(fn: Callable[[], T], *, retries: int = 3, backoff_s: float = 4.0,
                 what: str = "operation",
                 on_error: Optional[Callable[[int, Exception], None]] = None) -> T:
    """Retry transient navigation/parse failures. SessionExpired is never retried."""
    last: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return fn()
        except SessionExpired:
            raise
        except SectionUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - we classify in the report
            last = exc
            log.warning("%s failed (attempt %d/%d): %s", what, attempt, retries, exc)
            if on_error:
                try:
                    on_error(attempt, exc)
                except Exception:  # pragma: no cover
                    pass
            if attempt < retries:
                time.sleep(backoff_s * attempt)
    assert last is not None
    raise last
