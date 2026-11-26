"""Analytics > Followers: total followers and new followers."""
from __future__ import annotations

from typing import List

from .. import dom
from ..catalog import CATALOG
from .base import RunContext, Section, capture_many


class FollowersSection(Section):
    key = "followers"
    title = "Page Analytics > Followers"
    categories = ["Followers"]
    default_path = "/admin/analytics/followers/"
    nav_keywords = ["follower"]

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        names = next(n for c, _s, n in CATALOG if c == "Followers")
        capture_many(ctx, "Followers", names, url=url, section=self.title,
                     empty_states=empties)
        ctx.save_json("followers_tables", dom.tables(ctx.page))
