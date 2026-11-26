"""Analytics > Visitors: page views, unique visitors, custom button clicks,
plus the five visitor-demographic breakdowns.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from playwright.sync_api import Error as PwError, TimeoutError as PwTimeout

from .. import dom
from ..catalog import CATALOG, DEMOGRAPHIC_OPTIONS
from ..models import Limitation
from .base import RunContext, Section, capture_many, record_buckets

DEMO_SCOPE_HINTS = ("demographic", "visitor")


class VisitorsSection(Section):
    key = "visitors"
    title = "Page Analytics > Visitors"
    categories = ["Visitors"]            # prefix-matches "Visitors > Demographics"
    default_path = "/admin/analytics/visitors/"
    nav_keywords = ["visitor"]

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        names = next(n for c, _s, n in CATALOG if c == "Visitors")
        capture_many(ctx, "Visitors", names, url=url, section=self.title,
                     empty_states=empties)

        tables = dom.tables(ctx.page)
        ctx.cache["visitors_tables"] = tables
        ctx.cache["visitors_url"] = url
        ctx.save_json("visitors_tables", tables)

        self._demographics(ctx, url, empties)

    # ----------------------------------------------------------------- demo
    def _demographics(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        section = "Page Analytics > Visitors > Visitor demographics"
        category = "Visitors > Demographics"
        captured: Dict[str, Any] = {}

        for dim, options in DEMOGRAPHIC_OPTIONS.items():
            metric = ctx.metrics.require(category, dim, section)
            metric.date_range = ctx.date_range
            selected = self._select_dimension(ctx, options)
            if not selected:
                metric.fail(
                    f"The visitor-demographics selector did not offer {options[0]!r} "
                    f"(tried: {options}).",
                    Limitation.LINKEDIN_UI, url=url)
                continue
            dom.settle(ctx.page, settle_ms=1800, scroll_passes=1)
            buckets = self._read_buckets(ctx, selected)
            if not buckets:
                if empties or dom.empty_states(ctx.page):
                    metric.fail(
                        f"{selected!r} selected but LinkedIn rendered no demographic rows "
                        f"(empty state / insufficient data for this range).",
                        Limitation.DATA_UNAVAILABLE, url=url)
                else:
                    metric.fail(
                        f"{selected!r} selected but no label/value rows could be parsed "
                        f"from the demographics module.",
                        Limitation.AUTOMATION_FAILURE, url=url)
                continue
            record_buckets(ctx, category, dim, buckets, url=url, section=section,
                           strategy=f"demographics-dropdown:{selected}")
            captured[dim] = buckets
            ctx.shot(f"visitors_demographics_{dim.lower().replace(' ', '_')}")

        ctx.save_json("visitors_demographics", captured)

    def _select_dimension(self, ctx: RunContext, options: List[str]) -> str:
        """Choose a dimension in the visitor-demographics selector.

        Live markup: an artdeco dropdown trigger whose accessible name is
        "Visitor demographics, <current dimension>".
        """
        page = ctx.page
        # native <select> (other LinkedIn surfaces)
        for opt in options:
            try:
                sel = page.locator("select:visible").first
                if sel.count():
                    values = [o.strip() for o in sel.locator("option").all_text_contents()]
                    match = next((v for v in values if v.lower().startswith(opt.lower())), "")
                    if match:
                        sel.select_option(label=match)
                        return match
            except Exception:  # noqa: BLE001
                pass

        # The real control is the artdeco dropdown trigger whose accessible name
        # is "Visitor demographics, <current dimension>" — NOT the sibling
        # "more information about ..." tooltip button. (Playwright's role engine
        # does not see these artdeco buttons, so match the attribute directly.)
        try:
            trigger = page.locator(
                "button[aria-label^='Visitor demographics'], "
                "button[aria-label^='Follower demographics']").first
            has_trigger = trigger.count() > 0
            current = (trigger.get_attribute("aria-label") or "") if has_trigger else ""
        except (PwError, PwTimeout):
            has_trigger, current = False, ""

        for opt in options:
            if current and opt.lower() in current.lower():
                return opt

        if has_trigger:
            for opt in options:
                try:
                    trigger.click(timeout=8000)
                    page.wait_for_timeout(1800)   # artdeco dropdown animates open
                except (PwError, PwTimeout):
                    break
                if (dom.click_own_text(page, rf"^{re.escape(opt)}s?$")
                        or dom.click_text(page, rf"^{re.escape(opt)}s?$")):
                    page.wait_for_timeout(1500)
                    return opt
                try:
                    page.keyboard.press("Escape")
                except PwError:
                    pass

        # last resort: a visible pill/tab with that exact label
        for opt in options:
            if dom.click_text(ctx.page, rf"^{re.escape(opt)}s?$"):
                return opt
        return ""

    def _read_buckets(self, ctx: RunContext, selected: str) -> List[Dict[str, str]]:
        for scope in (selected, *DEMO_SCOPE_HINTS):
            bd = dom.breakdown(ctx.page, scope)
            rows = (bd or {}).get("rows") or []
            rows = [r for r in rows if r.get("label") and not
                    re.fullmatch(r"(page views|unique visitors|total)", r["label"], re.I)]
            if len(rows) >= 2:
                return rows[:40]
        return []
