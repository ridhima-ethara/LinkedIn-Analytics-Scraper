"""Life page metrics.

LinkedIn does not give the Life tab its own analytics page; its traffic is
reported inside Visitors > "Page views by page" (one row per page section).
This section reuses the Visitors tables when they were already captured, and
re-opens Visitors otherwise.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .. import dom, table_utils as tu
from ..models import Limitation
from .base import RunContext, Section, capture

CATEGORY = "Life Page"


class LifePageSection(Section):
    key = "life_page"
    title = "Page Analytics > Visitors > Page views by page"
    categories = [CATEGORY]
    default_path = "/admin/analytics/visitors/"
    nav_keywords = ["visitor"]

    def open(self, ctx: RunContext) -> str:
        """Reuse the Visitors page if the Visitors section already parsed it."""
        if ctx.cache.get("visitors_tables"):
            url = ctx.cache.get("visitors_url", "")
            ctx.note("[life_page] reusing tables captured on the Visitors tab")
            return url
        return super().open(ctx)

    def prepare(self, ctx: RunContext, url: str) -> List[str]:
        if ctx.cache.get("visitors_tables"):
            return ctx.cache.get("visitors_empties", [])
        return super().prepare(ctx, url)

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        tables = ctx.cache.get("visitors_tables") or dom.tables(ctx.page)
        table = (tu.find_table(tables, ["page views"], any_of=["page", "tab"])
                 or tu.find_table(tables, ["page"], any_of=["views"]))
        rows: List[Dict[str, Any]] = tu.row_dicts(table) if table else []
        life = tu.find_row(rows, r"\blife\b") if rows else None

        for name in ("Page Views", "Unique Visitors", "Last Updated"):
            m = ctx.metrics.require(CATEGORY, name, self.title)
            m.date_range = ctx.date_range
            if not table:
                m.fail("No 'Page views by page' table was rendered on the Visitors tab, so "
                       "Life-page traffic is not exposed anywhere in the admin UI.",
                       Limitation.LINKEDIN_UI, url=url)
                continue
            if not life:
                m.fail("The 'Page views by page' table contains no 'Life page' row — the Life "
                       "tab is either not published for this page or had no traffic in range.",
                       Limitation.DATA_UNAVAILABLE, url=url,
                       evidence="; ".join(" | ".join(r.get("_cells", [])) for r in rows[:4]))
                continue

            col = {"Page Views": ("page views", "views"),
                   "Unique Visitors": ("unique visitors", "unique"),
                   "Last Updated": ("last updated", "updated", "last edited")}[name]
            raw = tu.pick(life, *col)
            if raw in (None, "", "-", "—"):
                m.fail(f"The Life page row has no '{name}' column value "
                       f"(headers present: {table.get('headers')}).",
                       Limitation.LINKEDIN_UI, url=url,
                       evidence=" | ".join(life.get("_cells", [])))
                continue
            if name == "Last Updated":
                m.ok(raw, raw, url=url, unit="date", strategy="visitors-table:life-row",
                     evidence=" | ".join(life.get("_cells", [])))
                continue
            value = dom.parse_number(raw)
            if value is None:
                m.fail(f"Life page '{name}' cell {raw!r} is not numeric.",
                       Limitation.AUTOMATION_FAILURE, url=url)
            else:
                m.ok(value, raw, url=url, strategy="visitors-table:life-row",
                     unit=dom.unit_for(raw), evidence=" | ".join(life.get("_cells", [])))

        if life:
            ctx.save_json("life_page_row", life)
        # The Life tab's own "last updated" is sometimes only on the public Life tab.
        if not life:
            capture(ctx, CATEGORY, "Last Updated", url=url, section=self.title,
                    labels=["Last updated", "Last edited"], mode="text")
