"""Analytics > Search appearances: search count, top keywords, searcher demographics."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .. import dom, table_utils as tu
from ..models import Limitation
from .base import RunContext, Section, capture, record_buckets

CATEGORY = "Search Appearance"
SEARCHER_DIMENSIONS = ["Company", "Job title", "Industry", "Location", "Seniority",
                       "Company size", "Job function"]


class SearchAppearancesSection(Section):
    key = "search_appearances"
    title = "Page Analytics > Search appearances"
    categories = [CATEGORY]
    default_path = "/admin/analytics/search-appearances/"
    nav_keywords = ["search appearance", "search"]
    url_candidates = ["/admin/analytics/search_appearances/",
                      "/admin/analytics/search-appearances/"]

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        capture(ctx, CATEGORY, "Page Searches", url=url, section=self.title,
                empty_states=empties)
        self._keywords(ctx, url, empties)
        self._searcher_demographics(ctx, url, empties)

    # ------------------------------------------------------------ keywords
    def _keywords(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        tables = dom.tables(ctx.page)
        ctx.save_json("search_appearances_tables", tables)
        buckets: List[Dict[str, str]] = []
        strategy = ""

        kw_table = tu.find_table(tables, ["keyword"])
        if kw_table:
            for rec in tu.row_dicts(kw_table):
                cells = rec.get("_cells", [])
                if not cells:
                    continue
                label = cells[0]
                value = next((c for c in cells[1:] if dom.parse_number(c) is not None), "")
                buckets.append({"label": label, "value": value or "n/a"})
            strategy = "search-appearances:keywords-table"
        else:
            bd = dom.breakdown(ctx.page, "keyword")
            rows = (bd or {}).get("rows") or []
            if rows:
                buckets = rows[:40]
                strategy = "search-appearances:keywords-breakdown"

        metric = ctx.metrics.require(CATEGORY, "Top Keywords", self.title)
        metric.date_range = ctx.date_range
        if buckets:
            # keyword "values" may be absent in the UI (keyword list only)
            numeric = [b for b in buckets if dom.parse_number(b["value"]) is not None]
            if numeric:
                record_buckets(ctx, CATEGORY, "Top Keywords", numeric, url=url,
                               section=self.title, strategy=strategy)
            else:
                metric.partial(
                    [b["label"] for b in buckets],
                    "Keyword terms are listed but LinkedIn does not render a search count "
                    "per keyword in this view.",
                    Limitation.LINKEDIN_UI, url=url, strategy=strategy,
                    evidence="; ".join(b["label"] for b in buckets[:6]),
                    detail={"keywords": [b["label"] for b in buckets]})
        else:
            # Live UI (Nov 2026) renders a bare keyword list with no per-keyword
            # count, e.g. "Top keywords to find your Page: Ethara / 15rock / Ai".
            listing = dom.list_after_heading(ctx.page, r"top keywords", 25)
            items = (listing or {}).get("items") or []
            if items:
                metric.partial(
                    items,
                    "LinkedIn lists the top keywords but publishes no search count per "
                    "keyword in this view, so only the terms could be captured.",
                    Limitation.LINKEDIN_UI, url=url,
                    strategy="search-appearances:keyword-list",
                    evidence="; ".join(items[:8]),
                    detail={"keywords": items, "heading": (listing or {}).get("heading")})
            elif empties:
                metric.fail(f"No keyword list rendered; LinkedIn empty state: {empties[0]!r}.",
                            Limitation.DATA_UNAVAILABLE, url=url)
            else:
                metric.fail("No keyword table, breakdown or keyword list was found on the "
                            "Search appearances tab.", Limitation.LINKEDIN_UI, url=url)

    # -------------------------------------------------------- demographics
    def _searcher_demographics(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        metric = ctx.metrics.require(CATEGORY, "Top Page Searcher Demographics", self.title)
        metric.date_range = ctx.date_range
        found: Dict[str, List[Dict[str, str]]] = {}

        for dim in SEARCHER_DIMENSIONS:
            bd = dom.breakdown(ctx.page, dim)
            rows = [r for r in ((bd or {}).get("rows") or [])
                    if r.get("label") and not re.fullmatch(
                        r"(page searches|search appearances|total)", r["label"], re.I)]
            if len(rows) >= 2:
                found[dim] = rows[:25]

        if not found:
            listing = dom.list_after_heading(ctx.page, r"top page searcher demographics", 30)
            items = (listing or {}).get("items") or []
            if items:
                metric.partial(
                    items,
                    "LinkedIn lists the top searcher demographics (e.g. companies) without "
                    "a count or share per row in this view, so only the labels could be "
                    "captured.",
                    Limitation.LINKEDIN_UI, url=url,
                    strategy="search-appearances:searcher-list",
                    evidence="; ".join(items[:8]),
                    detail={"searcher_rows": items,
                            "heading": (listing or {}).get("heading")})
                ctx.save_json("search_appearances_searchers", {"list": items})
                return
            if empties:
                metric.fail(
                    f"No searcher-demographic module rendered; LinkedIn empty state: "
                    f"{empties[0]!r}.", Limitation.DATA_UNAVAILABLE, url=url)
            else:
                metric.fail(
                    "No searcher-demographic breakdown (company / job title / industry / "
                    "location / seniority) was present on the Search appearances tab.",
                    Limitation.LINKEDIN_UI, url=url)
            return

        total = sum(len(v) for v in found.values())
        metric.ok(total, f"{total} rows across {len(found)} dimension(s)", url=url,
                  unit="buckets", strategy="search-appearances:searcher-breakdowns",
                  evidence="; ".join(f"{k}: {v[0]['label']}={v[0]['value']}"
                                     for k, v in list(found.items())[:3]),
                  detail={"dimensions": found})
        for dim, rows in found.items():
            record_buckets(ctx, f"{CATEGORY} > Searcher {dim}", dim, rows, url=url,
                           section=self.title,
                           strategy="search-appearances:searcher-breakdowns")
        ctx.save_json("search_appearances_searchers", found)
