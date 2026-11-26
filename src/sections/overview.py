"""Analytics > Overview: search appearances, new followers, post impressions, visitors.

This LinkedIn build has no "Overview" analytics tab; the four headline figures
live on the admin dashboard as cards of the form
"73k / Search appearances / 5.7% / last 7 days" — each with its OWN period,
which is read off the card rather than inherited from the page filter.
"""
from __future__ import annotations

import re
from typing import List

from .. import dom
from ..catalog import CATALOG
from ..models import Status
from .base import RunContext, Section, capture_many


class OverviewSection(Section):
    key = "overview"
    title = "Page Analytics > Overview"
    categories = ["Overview"]
    default_path = "/admin/analytics/"
    nav_keywords = ["overview"]
    url_candidates = ["/admin/analytics/overview/", "/admin/dashboard/", "/admin/"]

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        names = next(n for c, _s, n in CATALOG if c == "Overview")
        metrics = capture_many(ctx, "Overview", names, url=url, section=self.title,
                               empty_states=empties)
        # Each dashboard card states its own window ("last 7 days"); prefer that
        # over the page-level filter so the reported range is the true one.
        for m in metrics:
            if m.status != Status.EXTRACTED:
                continue
            own = re.search(r"(last|past)\s+\d+\s+(day|days|month|months|year)",
                            m.evidence or "", re.I)
            if own:
                m.date_range = own.group(0)
                m.detail["period_source"] = "per-card label on the dashboard"
        ctx.save_json("overview_tables", dom.tables(ctx.page))
