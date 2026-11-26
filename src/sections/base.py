"""Section framework: navigation, date-range handling, metric capture,
and honest failure attribution.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from playwright.sync_api import Error as PwError, Page, TimeoutError as PwTimeout

from .. import dates, dom
from ..catalog import allows_percent, labels_for
from ..config import Config
from ..dom import SectionUnavailable, SessionExpired, with_retries
from ..logging_setup import get_logger
from ..models import Limitation, Metric, MetricSet, Status

log = get_logger("section")

DATE_PRESETS = {
    "past_7_days": ["Past 7 days", "Last 7 days"],
    "past_30_days": ["Last 30 days", "Past 30 days", "Past 28 days", "Last 28 days"],
    "past_28_days": ["Past 28 days", "Last 28 days", "Past 30 days", "Last 30 days",
                     "Past month", "Last month", "Past 1 month"],
    "past_90_days": ["Past 90 days", "Last 90 days", "Past 3 months"],
    "past_365_days": ["Past 365 days", "Past 12 months", "Last 365 days", "Past year"],
}

_PERMISSION_PATS = re.compile(
    r"(don.?t have (access|permission)|not authorized|only (page )?admins|"
    r"request admin access|page not found|does not exist|doesn.?t exist)", re.I
)


@dataclass
class RunContext:
    cfg: Config
    page: Page
    metrics: MetricSet
    out_dir: Path
    run_id: str
    date_range: str = ""
    requested_range: str = ""
    date_window: Optional[Tuple[date, date]] = None
    date_window_applied: Optional[Tuple[date, date]] = None
    date_range_verified: Optional[bool] = None
    date_range_explanation: str = ""
    nav_map: Dict[str, str] = field(default_factory=dict)
    posts: List[Dict[str, Any]] = field(default_factory=list)
    cache: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    section_status: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    screenshots: List[str] = field(default_factory=list)

    # -- paths ------------------------------------------------------------
    def shot(self, name: str) -> Optional[str]:
        if not self.cfg.output.get("save_screenshots", True):
            return None
        path = self.out_dir / "screenshots" / f"{name}.png"
        p = dom.screenshot(self.page, path)
        if p:
            self.screenshots.append(p)
        return p

    def save_text(self, name: str, text: str) -> None:
        if not self.cfg.output.get("save_page_text", True):
            return
        path = self.out_dir / "page_text" / f"{name}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8")

    def save_json(self, name: str, payload: Any) -> None:
        path = self.out_dir / "evidence" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def note(self, msg: str) -> None:
        log.info("note: %s", msg)
        self.notes.append(msg)


# --------------------------------------------------------------------------
# date range
# --------------------------------------------------------------------------
def _open_date_control(page) -> bool:
    """Open LinkedIn's date-range control.

    Matching is restricted to buttons whose accessible name starts with
    "Date range" or whose entire label is a range/preset. A looser text match
    would click dashboard metric cards (their labels contain "last 7 days")
    and navigate away from the page being extracted.
    """
    how = dom.click_date_control(page)
    if how:
        log.debug("opened the date control by %s", how)
        page.wait_for_timeout(1200)
        return True
    return False


def _read_shown_label(page) -> str:
    labels = dom.date_range_labels(page)
    for lab in labels:
        if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}\s*[-–]", lab) or \
                re.search(r"[-–]\s*[A-Z][a-z]{2}", lab):
            return lab
    return labels[0] if labels else ""


def _confirm_date_picker(page) -> None:
    for pattern in (r"^(apply|update|done|save|show results)$", r"apply|update|done"):
        if dom.click_text(page, pattern):
            break
    page.wait_for_timeout(1500)


def _visible_calendar_month(page) -> Optional[Tuple[int, int]]:
    """(year, month) of the first day cell currently rendered in the panel."""
    label = page.evaluate(r"""() => {
      const b = Array.from(document.querySelectorAll('button[aria-label]'))
        .find(x => /^[A-Za-z]+day, [A-Za-z]+ \d{1,2}, \d{4}/.test(x.getAttribute('aria-label')));
      return b ? b.getAttribute('aria-label') : '';
    }""")
    d = dates.parse_date(re.sub(r"^[A-Za-z]+day,\s*", "", label or "").rstrip("."))
    return (d.year, d.month) if d else None


def _ensure_month_visible(page, target: date, max_steps: int = 24) -> bool:
    """Page the calendar until `target`'s month is rendered."""
    month_sel = (f"button[aria-label*='{target.strftime('%B')} ']"
                 f"[aria-label*=', {target.year}']")
    for _ in range(max_steps):
        try:
            if page.locator(month_sel).count():
                return True
        except (PwError, PwTimeout):
            return False
        current = _visible_calendar_month(page)
        if not current:
            log.debug("no day cell rendered; is the date panel open?")
            return False
        direction = "Previous month" if (target.year, target.month) < current else "Next month"
        try:
            nav = page.locator(f"button[aria-label='{direction}']").first
            if not nav.count() or not nav.is_enabled():
                return False
            nav.click(timeout=6000)
            page.wait_for_timeout(350)
        except (PwError, PwTimeout):
            return False
    return False


def _click_day(page, target: date, slack_days: int = 0) -> Optional[date]:
    """Click the day cell for `target`, walking back up to `slack_days` if that
    day is not selectable (LinkedIn's analytics data lags ~2 days)."""
    for back in range(slack_days + 1):
        day = target - timedelta(days=back)
        if not _ensure_month_visible(page, day):
            continue
        sel = f"button[aria-label*='{day.strftime('%B')} {day.day}, {day.year}']"
        try:
            cell = page.locator(sel).first
            if cell.count() and cell.is_enabled():
                cell.click(timeout=6000)
                page.wait_for_timeout(500)
                return day
        except (PwError, PwTimeout) as exc:
            log.debug("day cell %s not clickable: %s", day, exc)
    return None


def _apply_custom_window(ctx: RunContext, section_key: str,
                         window: Tuple[date, date]) -> bool:
    """Enter an explicit start/end window in LinkedIn's date-range panel.

    On the current admin build the two `mm/dd/yyyy` inputs are **disabled**
    (display only), so the range must be set by clicking day cells in the
    two-month grid and confirming with "Update". Editable inputs are still
    tried first, since other LinkedIn surfaces expose them.
    """
    page = ctx.page
    start, end = window
    if not _open_date_control(page):
        ctx.note(f"[{section_key}] no date-range control found; cannot request "
                 f"{dates.window_label(window)}")
        return False

    dom.click_text(page, r"^custom(\s+(date\s+)?range)?$")
    page.wait_for_timeout(600)

    filled = 0
    applied_start: Optional[date] = None
    applied_end: Optional[date] = None

    # 1) editable date inputs, when the build offers them
    try:
        boxes = page.locator("input[placeholder='mm/dd/yyyy']:visible")
        if boxes.count() == 0:
            boxes = page.locator("input[type='date']:visible")
        if boxes.count() >= 2 and boxes.nth(0).is_editable():
            for idx, value in ((0, start), (1, end)):
                box = boxes.nth(idx)
                box.fill(value.strftime("%m/%d/%Y"), timeout=5000)
                page.keyboard.press("Enter")
                page.wait_for_timeout(600)
                filled += 1
            applied_start, applied_end = start, end
    except (PwError, PwTimeout) as exc:
        log.debug("date inputs not usable: %s", exc)

    # 2) inputs identified by accessible name
    if filled < 2:
        filled = 0
        for which, value in (("start|from|begin", start), ("end|to|through", end)):
            try:
                loc = page.locator("input:visible")
                for k in range(min(loc.count(), 12)):
                    cand = loc.nth(k)
                    meta = " ".join(filter(None, [
                        cand.get_attribute("aria-label") or "",
                        cand.get_attribute("placeholder") or "",
                        cand.get_attribute("name") or "",
                        cand.get_attribute("id") or ""]))
                    if re.search(which, meta, re.I) and cand.is_editable():
                        cand.fill(value.strftime("%m/%d/%Y"), timeout=5000)
                        page.wait_for_timeout(400)
                        filled += 1
                        break
            except (PwError, PwTimeout) as exc:
                log.debug("named date input (%s) failed: %s", which, exc)
        if filled == 2:
            applied_start, applied_end = start, end

    # 3) the day grid (current LinkedIn admin build)
    if filled < 2:
        applied_start = _click_day(page, start, slack_days=3)
        applied_end = _click_day(page, end, slack_days=5)
        filled = sum(1 for d in (applied_start, applied_end) if d)
        if applied_start and applied_start != start:
            ctx.note(f"[{section_key}] start {start} was not selectable in LinkedIn's "
                     f"calendar; the nearest selectable day {applied_start} was used")
        if applied_end and applied_end != end:
            ctx.note(f"[{section_key}] end {end} was not selectable (LinkedIn's analytics "
                     f"data lags a few days); the nearest selectable day {applied_end} "
                     f"was used")

    if filled >= 2:
        _confirm_date_picker(page)
        if applied_start and applied_end:
            ctx.date_window_applied = (applied_start, applied_end)
        return True

    ctx.note(f"[{section_key}] LinkedIn's date panel exposed no editable start/end inputs "
             f"and no selectable day cells ({filled}/2 set); the requested window "
             f"{dates.window_label(window)} was not entered")
    try:
        page.keyboard.press("Escape")
    except PwError:
        pass
    return False


def _apply_preset(ctx: RunContext, section_key: str, preset: str) -> str:
    """Click a rolling preset; return the preset label that was clicked."""
    page = ctx.page
    wanted = DATE_PRESETS.get(preset, [])
    if not wanted:
        return ""
    if not _open_date_control(page):
        ctx.note(f"[{section_key}] no date-range control found; using the page default range")
        return ""
    page.wait_for_timeout(1200)
    applied = ""
    for label in wanted:
        if dom.click_text(page, rf"^{re.escape(label)}$"):
            applied = label
            break
    if not applied:
        for label in wanted:
            if dom.click_text(page, re.escape(label)):
                applied = label
                break
    if applied:
        dom.settle(page, settle_ms=int(ctx.cfg.extraction.get("settle_ms", 2500)),
                   scroll_passes=2)
        log.info("[%s] date filter set to %r", section_key, applied)
    else:
        try:
            page.keyboard.press("Escape")
        except PwError:
            pass
        ctx.note(f"[{section_key}] date-range option {wanted[0]!r} not offered by the UI; "
                 f"using the page default range")
    return applied


def apply_date_range(ctx: RunContext, section_key: str) -> str:
    """Set the on-page date filter; return the label LinkedIn actually shows.

    The label is read back from the UI, never assumed. When a custom window
    (e.g. a calendar year) is requested it is verified against that label, and
    `ctx.date_range_verified` records whether LinkedIn really applied it.
    """
    page = ctx.page
    ex = ctx.cfg.extraction
    preset = str(ex.get("date_range", "keep_default"))
    applied = ""
    window = ctx.date_window

    if window:
        days = dates.window_days(window)
        if days > dates.MAX_WINDOW_DAYS:
            ctx.note(f"[{section_key}] requested window {dates.window_label(window)} spans "
                     f"{days} days; LinkedIn Page analytics supports at most "
                     f"{dates.MAX_WINDOW_DAYS} days, so the full window cannot be applied")
        if _apply_custom_window(ctx, section_key, window):
            applied = dates.window_label(window)
            dom.settle(page, settle_ms=int(ex.get("settle_ms", 2500)), scroll_passes=2)
            log.info("[%s] custom date window requested: %s", section_key, applied)
        else:
            fallback = dates.nearest_preset(window)
            ctx.note(f"[{section_key}] falling back to the rolling preset {fallback!r}; "
                     f"the reported date range is whatever LinkedIn displays, not the "
                     f"requested {dates.window_label(window)}")
            applied = _apply_preset(ctx, section_key, fallback)
    elif preset in DATE_PRESETS:
        applied = _apply_preset(ctx, section_key, preset)

    shown = _read_shown_label(page)
    resolved = shown or applied or "unknown (LinkedIn default range)"

    if window:
        ok, explanation = dates.verify_applied(shown, ctx.date_window_applied or window)
        ctx.date_range_verified = ok
        if ctx.date_range_explanation != explanation:
            ctx.date_range_explanation = explanation
            ctx.note(f"[{section_key}] date-window check: {explanation}")
        if not ok:
            resolved = f"{resolved} [requested {dates.window_label(window)} — NOT CONFIRMED]"
    return resolved


# --------------------------------------------------------------------------
# metric capture
# --------------------------------------------------------------------------
def capture(ctx: RunContext, category: str, name: str, *, url: str, section: str,
            labels: Optional[Sequence[str]] = None, mode: str = "number",
            empty_states: Optional[List[str]] = None, entity: str = "",
            unit: str = "") -> Metric:
    """Read one label-anchored metric off the current page, or record why not."""
    m = ctx.metrics.require(category, name, section, entity)
    m.source_section = section
    m.date_range = ctx.date_range
    lbls = list(labels or labels_for(category, name))
    hit = dom.find_metric(ctx.page, lbls, mode,
                          allow_percent=allows_percent(category, name))
    if not hit or not hit.get("raw"):
        if empty_states:
            m.fail(
                f"LinkedIn shows an empty state on this section ({empty_states[0]!r}), so no "
                f"value is rendered for label(s) {lbls}.",
                Limitation.DATA_UNAVAILABLE, url=url, evidence="; ".join(empty_states[:3]),
            )
        else:
            m.fail(
                f"No element labelled {lbls} was present on the rendered page.",
                Limitation.LINKEDIN_UI, url=url,
            )
        return m

    raw = hit["raw"]
    if mode == "number":
        value = dom.parse_number(raw)
        if value is None:
            return m.fail(
                f"Label {hit['label']!r} found but the adjacent text {raw!r} is not numeric.",
                Limitation.AUTOMATION_FAILURE, url=url, evidence=hit.get("evidence", ""),
            )
        return m.ok(value, raw, url=url, evidence=hit.get("evidence", ""),
                    strategy=f"label-anchor:{hit['label']}@depth{hit.get('depth')}",
                    unit=unit or dom.unit_for(raw))
    return m.ok(raw, raw, url=url, evidence=hit.get("evidence", ""),
                strategy=f"label-anchor-text:{hit['label']}@depth{hit.get('depth')}",
                unit=unit or "text")


def capture_many(ctx: RunContext, category: str, names: Sequence[str], *, url: str,
                 section: str, empty_states: Optional[List[str]] = None,
                 mode: str = "number") -> List[Metric]:
    return [capture(ctx, category, n, url=url, section=section,
                    empty_states=empty_states, mode=mode) for n in names]


def record_buckets(ctx: RunContext, category: str, name: str, buckets: List[Dict[str, str]],
                   *, url: str, section: str, strategy: str) -> None:
    """Store a demographic/keyword breakdown as a summary row + one row per bucket."""
    summary = ctx.metrics.require(category, name, section)
    summary.date_range = ctx.date_range
    if not buckets:
        summary.fail(f"No breakdown rows could be read for {name!r}.",
                     Limitation.LINKEDIN_UI, url=url)
        return
    summary.ok(len(buckets), f"{len(buckets)} buckets", url=url, strategy=strategy,
               unit="buckets",
               evidence="; ".join(
                   f"{b['label']}={b['value']}"
                   + (f" ({b['percent']})" if b.get("percent") else "")
                   for b in buckets[:5]),
               detail={"buckets": buckets})
    for b in buckets:
        row = ctx.metrics.require(category, name, section, entity=b["label"])
        row.date_range = ctx.date_range
        parsed = dom.parse_number(b["value"])
        if parsed is None:
            row.fail(f"Bucket {b['label']!r} rendered a non-numeric value {b['value']!r}.",
                     Limitation.AUTOMATION_FAILURE, url=url)
        else:
            extra = {"share_percent": b["percent"]} if b.get("percent") else None
            row.ok(parsed, b["value"], url=url, strategy=strategy,
                   unit=dom.unit_for(b["value"]),
                   evidence=f"{b['label']} {b['value']}"
                            + (f" ({b['percent']})" if b.get("percent") else ""),
                   detail=extra)


# --------------------------------------------------------------------------
# section base
# --------------------------------------------------------------------------
class Section:
    key: str = ""
    title: str = ""
    categories: List[str] = []
    default_path: str = ""
    nav_keywords: List[str] = []          # text used to recognise the tab in LinkedIn's nav
    url_candidates: List[str] = []        # extra paths to try if the first 404s

    # -- url resolution ---------------------------------------------------
    def urls(self, ctx: RunContext) -> List[str]:
        cfg = ctx.cfg
        urls = [cfg.section_url(self.key, self.default_path)]
        for kw in self.nav_keywords:
            for text, href in ctx.nav_map.items():
                if kw.lower() in text.lower() and href not in urls:
                    urls.append(href)
        for path in self.url_candidates:
            u = f"{cfg.company_base}{path}"
            if u not in urls:
                urls.append(u)
        return urls

    # -- lifecycle --------------------------------------------------------
    def open(self, ctx: RunContext) -> str:
        """Navigate to the first URL that renders. Raise SectionUnavailable otherwise."""
        ex = ctx.cfg.extraction
        last_reason = ""
        for url in self.urls(ctx):
            dom.goto(ctx.page, url,
                     timeout_ms=int(ctx.cfg.browser.get("nav_timeout_ms", 60000)),
                     settle_ms=int(ex.get("settle_ms", 2500)),
                     scroll_passes=int(ex.get("scroll_passes", 6)))
            text = dom.page_text(ctx.page)
            wall = _PERMISSION_PATS.search(text[:4000] or "")
            if wall:
                last_reason = (f"LinkedIn returned an access/not-found page at {url} "
                               f"(matched {wall.group(0)!r})")
                log.warning("%s", last_reason)
                continue
            # harvest nav links for later sections
            for link in dom.nav_links(ctx.page):
                ctx.nav_map.setdefault(link["text"], link["href"])
            return url
        raise SectionUnavailable(
            last_reason or f"none of the candidate URLs for '{self.key}' rendered",
            Limitation.PERMISSIONS if last_reason else Limitation.LINKEDIN_UI,
        )

    def prepare(self, ctx: RunContext, url: str) -> List[str]:
        """Expand pagination, apply the date filter, record page evidence."""
        ex = ctx.cfg.extraction
        ctx.date_range = apply_date_range(ctx, self.key) or ctx.date_range
        dom.expand_all(ctx.page, rounds=int(ex.get("expand_show_more_rounds", 8)))
        dom.settle(ctx.page, settle_ms=int(ex.get("settle_ms", 2500)), scroll_passes=2)
        empties = dom.empty_states(ctx.page)
        ctx.save_text(f"{self.key}", dom.page_text(ctx.page))
        ctx.shot(f"{self.key}")
        if empties:
            log.info("[%s] LinkedIn empty-state messages on page: %s", self.key, empties[:3])
        return empties

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        raise NotImplementedError

    # -- orchestration ----------------------------------------------------
    def run(self, ctx: RunContext) -> Dict[str, Any]:
        ex = ctx.cfg.extraction
        status: Dict[str, Any] = {"section": self.key, "title": self.title,
                                  "url": "", "outcome": "ok", "reason": ""}

        def attempt() -> None:
            url = self.open(ctx)
            status["url"] = url
            empties = self.prepare(ctx, url)
            status["empty_states"] = empties
            self.extract(ctx, url, empties)

        def on_error(attempt_no: int, exc: Exception) -> None:
            ctx.shot(f"{self.key}_failure_attempt{attempt_no}")

        try:
            with_retries(attempt, retries=int(ex.get("retries", 3)),
                         backoff_s=float(ex.get("retry_backoff_s", 4)),
                         what=f"section '{self.key}'", on_error=on_error)
        except SessionExpired:
            ctx.metrics.fail_section(
                self.categories,
                "Authenticated session expired/was challenged before this section could be read.",
                Limitation.SESSION_EXPIRED, url=status["url"])
            status.update(outcome="session_expired",
                          reason="session expired while opening the section")
            raise
        except SectionUnavailable as exc:
            ctx.metrics.fail_section(self.categories, str(exc), exc.limitation,
                                     url=status["url"])
            status.update(outcome="unavailable", reason=str(exc))
            ctx.shot(f"{self.key}_unavailable")
        except Exception as exc:  # noqa: BLE001
            reason = f"automation error in section '{self.key}': {type(exc).__name__}: {exc}"
            ctx.metrics.fail_section(self.categories, reason,
                                     Limitation.AUTOMATION_FAILURE, url=status["url"])
            status.update(outcome="error", reason=reason)
            log.error("%s", reason)

        counts = {s: 0 for s in (Status.EXTRACTED, Status.PARTIAL, Status.NOT_ACCESSIBLE)}
        for m in ctx.metrics.all():
            if any(m.category.startswith(c) for c in self.categories):
                counts[m.status] = counts.get(m.status, 0) + 1
        status["metric_counts"] = counts
        ctx.section_status[self.key] = status
        log.info("[%s] done: %s", self.key, counts)
        return status
