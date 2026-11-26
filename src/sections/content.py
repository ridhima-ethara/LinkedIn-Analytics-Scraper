"""Analytics > Content: aggregate engagement metrics + the post performance table.

The parsed post table is cached on the run context so the posts section can reuse
it without re-paginating; `parse_post_table` is also called directly by the posts
section when Content was not part of the run.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .. import dom, table_utils as tu
from ..catalog import CATALOG
from ..models import Limitation
from .base import RunContext, Section, capture_many


def parse_post_table(ctx: RunContext, url: str, empties: List[str]) -> List[Dict[str, Any]]:
    """Read the post performance table on the current page into post records."""
    tables = dom.tables(ctx.page)
    ctx.save_json("content_tables", tables)
    post_table = tu.find_table(tables, ["impressions"],
                               any_of=["post", "title", "date", "created"])
    rows: List[Dict[str, Any]] = tu.row_dicts(post_table) if post_table else []

    if not rows:
        reason = ("No post-performance table with an 'Impressions' column was rendered "
                  "on the Content tab")
        if empties:
            reason += f"; LinkedIn empty state present: {empties[0]!r}"
        ctx.note(f"[content] {reason}")
        ctx.cache["post_rows"] = []
        ctx.cache["post_rows_url"] = url
        ctx.cache["post_table_reason"] = reason
        ctx.cache["post_table_limitation"] = (
            Limitation.DATA_UNAVAILABLE if empties else Limitation.LINKEDIN_UI)
        return []

    posts: List[Dict[str, Any]] = []
    for rec in rows:
        # LinkedIn links each row to that post's own analytics page; using the
        # row's href is far more reliable than guessing a URL pattern.
        href = ""
        for link in rec.get("_links") or []:
            if link and ("post-analytics" in link or "post-summary" in link):
                href = link if link.startswith("http") else f"https://www.linkedin.com{link}"
                break
        title = (tu.pick(rec, "post title", "post", "title")
                 or (rec.get("_cells") or [""])[0])
        posts.append({
            "urn": rec.get("_urn", ""),
            "title": (title or "").strip()[:200],
            "post_type": tu.pick(rec, "post type", "type") or "",
            "created_by": tu.pick(rec, "created by", "author") or "",
            "date": tu.pick(rec, "date", "created", "posted") or "",
            "list_impressions": dom.parse_number(tu.pick(rec, "impressions")),
            "list_reactions": dom.parse_number(tu.pick(rec, "reactions")),
            "list_comments": dom.parse_number(tu.pick(rec, "comments")),
            "list_reposts": dom.parse_number(tu.pick(rec, "reposts", "shares")),
            "list_engagement_rate": dom.parse_number(
                tu.pick(rec, "engagement rate", "engagements rate")),
            "list_clicks": dom.parse_number(tu.pick(rec, "clicks")),
            "list_views": dom.parse_number(tu.pick(rec, "views")),
            "list_ctr": dom.parse_number(tu.pick(rec, "ctr", "click through")),
            "list_audience": tu.pick(rec, "audience") or "",
            "analytics_href": href,
            "source_url": url,
            "detail_status": "pending",
        })

    ctx.cache["post_rows"] = posts
    ctx.cache["post_rows_url"] = url
    ctx.cache["post_table_headers"] = post_table.get("headers", [])
    ctx.note(f"[content] post performance table captured: {len(posts)} row(s), "
             f"{sum(1 for p in posts if p['urn'])} with a post URN, "
             f"{sum(1 for p in posts if p['analytics_href'])} with a direct analytics link")
    return posts


class ContentSection(Section):
    key = "content"
    title = "Page Analytics > Content"
    categories = ["Content"]
    default_path = "/admin/analytics/updates/"
    nav_keywords = ["content", "updates"]
    url_candidates = ["/admin/analytics/content/", "/admin/analytics/updates/"]

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        names = next(n for c, _s, n in CATALOG if c == "Content")
        capture_many(ctx, "Content", names, url=url, section=self.title,
                     empty_states=empties)
        parse_post_table(ctx, url, empties)
