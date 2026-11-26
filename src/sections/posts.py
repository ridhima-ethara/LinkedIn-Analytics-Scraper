"""Individual post analytics (and video metrics) for each post on the page.

For every post found in Content > post performance, the post's own analytics
page is opened and each requested metric is read from it. Per-post rows are
emitted with `entity=<post urn>`; the catalog summary row reports *how many*
posts yielded that metric (never an invented aggregate) and carries the
per-post values in `detail.per_post`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .. import dates, dom
from ..catalog import CATALOG, labels_for
from ..dom import SectionUnavailable, SessionExpired
from ..logging_setup import get_logger
from ..models import Limitation, Status
from .base import RunContext, Section, capture

log = get_logger("section.posts")

POST_CATEGORY = "Individual Post Analytics"
VIDEO_CATEGORY = "Video Posts"
TEXT_MODE_METRICS = {"Watch Time", "Average Watch Time"}
MIN_LABELS_FOR_VALID_DETAIL = 2


class PostsSection(Section):
    key = "posts"
    title = "Page Analytics > Content > Post analytics"
    categories = [POST_CATEGORY, VIDEO_CATEGORY]
    default_path = "/admin/analytics/updates/"
    nav_keywords = ["content", "updates"]

    # ----------------------------------------------------------- lifecycle
    def open(self, ctx: RunContext) -> str:
        if ctx.cache.get("post_rows") is not None:
            return ctx.cache.get("post_rows_url") or ctx.section_status.get(
                "content", {}).get("url", "")
        return super().open(ctx)

    def prepare(self, ctx: RunContext, url: str) -> List[str]:
        if ctx.cache.get("post_rows") is not None:
            return []
        return super().prepare(ctx, url)

    def extract(self, ctx: RunContext, url: str, empties: List[str]) -> None:
        if "post_rows" not in ctx.cache:
            # the Content section was not part of this run: parse the table here
            from .content import parse_post_table
            parse_post_table(ctx, url, empties)
        posts: List[Dict[str, Any]] = list(ctx.cache.get("post_rows") or [])
        if not posts:
            reason = ctx.cache.get("post_table_reason") or (
                "No posts were listed in Content > post performance, so no individual post "
                "analytics exist to extract.")
            limitation = ctx.cache.get("post_table_limitation", Limitation.DATA_UNAVAILABLE)
            self._fail_all(ctx, reason, limitation, url)
            return

        if not ctx.cfg.extraction.get("post_detail", True):
            self._fail_all(ctx, "extraction.post_detail is disabled in the configuration.",
                           Limitation.NOT_ATTEMPTED, url)
            ctx.posts = posts
            return

        max_posts = int(ctx.cfg.extraction.get("max_posts", 10))
        candidates = self._filter_by_window(ctx, posts)
        selected = candidates[:max_posts]
        ctx.note(f"[posts] opening individual analytics for {len(selected)} of "
                 f"{len(candidates)} in-scope post(s) ({len(posts)} listed, "
                 f"extraction.max_posts={max_posts})")
        if ctx.date_window:
            ctx.note("[posts] NOTE: LinkedIn reports post-level metrics cumulatively "
                     "since each post was published and does not filter them by date "
                     "range; the window only selects WHICH posts are opened. Each "
                     "metric's date_range records what the post page displayed.")

        per_post: Dict[str, Dict[str, Any]] = {}
        failures: Dict[str, str] = {}

        for i, post in enumerate(selected, start=1):
            urn = post.get("urn", "")
            if not urn:
                post["detail_status"] = "no_urn"
                failures[post.get("title", f"row{i}")] = (
                    "No post URN was present in the Content table row, so the post's own "
                    "analytics page could not be addressed.")
                continue
            try:
                opened = self._open_post(ctx, urn, post.get("analytics_href", ""))
            except SessionExpired:
                raise
            except Exception as exc:  # noqa: BLE001
                post["detail_status"] = "open_failed"
                failures[urn] = f"navigation error: {type(exc).__name__}: {exc}"
                ctx.shot(f"post_{i}_open_failed")
                continue
            if not opened:
                post["detail_status"] = "unreachable"
                failures[urn] = ("None of the configured post-analytics URLs rendered a "
                                 "metrics page for this post (LinkedIn may not expose "
                                 "per-post analytics for it).")
                continue
            post_url, labels_seen = opened
            values = self._extract_post(ctx, post, post_url, i)
            per_post[urn] = values
            post["detail_status"] = "ok"
            post["detail_url"] = post_url
            post["labels_seen"] = labels_seen

        ctx.posts = posts
        ctx.save_json("post_detail_values", per_post)
        self._rollup(ctx, selected, per_post, failures, url)

    # ------------------------------------------------------------ helpers
    def _filter_by_window(self, ctx: RunContext, posts: List[Dict[str, Any]]
                          ) -> List[Dict[str, Any]]:
        """Keep posts published inside the requested window (plus undated ones)."""
        window = ctx.date_window
        if not window or not ctx.cfg.extraction.get("post_date_filter", True):
            for post in posts:
                post["date_in_window"] = "not_filtered"
            return posts
        inside: List[Dict[str, Any]] = []
        undated: List[Dict[str, Any]] = []
        outside = 0
        for post in posts:
            verdict = dates.in_window(post.get("date"), window)
            if verdict is True:
                post["date_in_window"] = True
                inside.append(post)
            elif verdict is None:
                post["date_in_window"] = "unparseable_date"
                undated.append(post)
            else:
                post["date_in_window"] = False
                post["detail_status"] = "outside_date_window"
                outside += 1
        ctx.note(f"[posts] date window {dates.window_label(window)}: "
                 f"{len(inside)} post(s) inside, {outside} excluded, "
                 f"{len(undated)} with an unparseable date (kept)")
        return inside + undated
    def _open_post(self, ctx: RunContext, urn: str,
                   href: str = "") -> Optional[Tuple[str, int]]:
        """Open a post's analytics view. Returns (url, number of known labels seen)."""
        ex = ctx.cfg.extraction
        probe_labels = ["Impressions", "Members reached", "Engagements", "Reactions",
                        "Clicks", "Engagement rate"]
        candidates = ([href] if href else []) + [
            tpl.replace("{urn}", urn) for tpl in ctx.cfg.post_summary_templates()]
        for url in candidates:
            try:
                dom.goto(ctx.page, url,
                         timeout_ms=int(ctx.cfg.browser.get("nav_timeout_ms", 60000)),
                         settle_ms=int(ex.get("settle_ms", 2500)), scroll_passes=2)
            except SessionExpired:
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("post url %s failed: %s", url, exc)
                continue

            text = dom.page_text(ctx.page)[:4000]
            if re.search(r"page not found|doesn.?t exist|no longer available", text, re.I):
                continue

            # a feed permalink needs its analytics view opened explicitly
            if "/feed/update/" in url:
                if not dom.click_text(ctx.page, r"view analytics|see analytics|^analytics$"):
                    continue
                dom.settle(ctx.page, settle_ms=2000, scroll_passes=2)

            seen = sum(1 for lab in probe_labels if dom.find_metric(ctx.page, [lab]))
            if seen >= MIN_LABELS_FOR_VALID_DETAIL:
                return ctx.page.url, seen
            log.debug("post url %s rendered only %d known label(s)", url, seen)
        return None

    def _extract_post(self, ctx: RunContext, post: Dict[str, Any], url: str,
                      index: int) -> Dict[str, Any]:
        urn = post["urn"]
        empties = dom.empty_states(ctx.page)
        ranges = dom.date_range_labels(ctx.page)
        post_range = ranges[0] if ranges else (f"since posted ({post.get('date')})"
                                               if post.get("date") else ctx.date_range)
        saved_range, ctx.date_range = ctx.date_range, post_range
        ctx.save_text(f"post_{index}_{urn.split(':')[-1]}", dom.page_text(ctx.page))
        ctx.shot(f"post_{index}_{urn.split(':')[-1]}")

        values: Dict[str, Any] = {}
        names = next(n for c, _s, n in CATALOG if c == POST_CATEGORY)
        for name in names:
            m = capture(ctx, POST_CATEGORY, name, url=url, section=self.title,
                        empty_states=empties, entity=urn)
            values[name] = m.value
            m.detail.setdefault("post_title", post.get("title", ""))
            m.detail.setdefault("post_date", post.get("date", ""))

        is_video = bool(re.search(r"video", str(post.get("post_type", "")), re.I)) or \
            bool(dom.find_metric(ctx.page, labels_for(VIDEO_CATEGORY, "Video Views")))
        post["is_video"] = is_video
        video_names = next(n for c, _s, n in CATALOG if c == VIDEO_CATEGORY)
        for name in video_names:
            if not is_video:
                vm = ctx.metrics.require(VIDEO_CATEGORY, name, self.title, entity=urn)
                vm.date_range = post_range
                vm.fail(f"Post type is {post.get('post_type') or 'non-video'}; LinkedIn only "
                        f"reports {name} for video posts.",
                        Limitation.DATA_UNAVAILABLE, url=url)
                values[name] = None
                continue
            mode = "text" if name in TEXT_MODE_METRICS else "number"
            vm = capture(ctx, VIDEO_CATEGORY, name, url=url, section=self.title,
                         empty_states=empties, entity=urn, mode=mode)
            values[name] = vm.value

        ctx.date_range = saved_range
        post.update({f"detail_{k}": v for k, v in values.items()})
        return values

    def _rollup(self, ctx: RunContext, selected: List[Dict[str, Any]],
                per_post: Dict[str, Dict[str, Any]], failures: Dict[str, str],
                url: str) -> None:
        """Summarise each per-post metric across the posts that were opened."""
        attempted = len(selected)
        opened = len(per_post)
        for category in (POST_CATEGORY, VIDEO_CATEGORY):
            names = next(n for c, _s, n in CATALOG if c == category)
            applicable = [p for p in selected
                          if category != VIDEO_CATEGORY or p.get("is_video")]
            for name in names:
                summary = ctx.metrics.require(category, name, self.title)
                summary.date_range = "per post (see detail.per_post)"
                got = {urn: vals.get(name) for urn, vals in per_post.items()
                       if vals.get(name) is not None}
                detail = {"posts_attempted": attempted, "posts_opened": opened,
                          "posts_with_value": len(got), "per_post": got,
                          "post_failures": failures}
                if not got:
                    if category == VIDEO_CATEGORY and not applicable:
                        summary.fail(
                            f"None of the {attempted} post(s) examined are video posts, so "
                            f"{name} is not reported by LinkedIn for them.",
                            Limitation.DATA_UNAVAILABLE, url=url)
                    elif opened == 0:
                        summary.fail(
                            f"No post analytics page could be opened "
                            f"({attempted} post(s) attempted). First reason: "
                            f"{next(iter(failures.values()), 'unknown')}",
                            Limitation.AUTOMATION_FAILURE, url=url)
                    else:
                        summary.fail(
                            f"{name} was not rendered on any of the {opened} post analytics "
                            f"page(s) that were opened.",
                            Limitation.LINKEDIN_UI, url=url)
                    summary.detail.update(detail)
                    continue

                expected = len(applicable) if applicable else opened
                if len(got) >= expected and not failures:
                    summary.ok(len(got), f"{len(got)} post(s)", url=url, unit="posts",
                               strategy="per-post rollup",
                               evidence="; ".join(f"{u.split(':')[-1]}={v}"
                                                  for u, v in list(got.items())[:4]),
                               detail=detail)
                else:
                    summary.partial(
                        len(got),
                        f"Captured for {len(got)} of {expected} applicable post(s); "
                        f"{len(failures)} post(s) could not be opened or lacked the metric.",
                        Limitation.LINKEDIN_UI if opened else Limitation.AUTOMATION_FAILURE,
                        url=url, unit="posts", strategy="per-post rollup",
                        evidence="; ".join(f"{u.split(':')[-1]}={v}"
                                           for u, v in list(got.items())[:4]),
                        detail=detail)

    def _fail_all(self, ctx: RunContext, reason: str, limitation: str, url: str) -> None:
        for category in (POST_CATEGORY, VIDEO_CATEGORY):
            names = next(n for c, _s, n in CATALOG if c == category)
            for name in names:
                m = ctx.metrics.require(category, name, self.title)
                if m.status != Status.EXTRACTED:
                    m.fail(reason, limitation, url=url)
