"""The complete catalog of requested metrics.

This is the contract for the reports: the extractor is only allowed to *promote*
entries in this catalog, never to invent values. Per-post metrics are also added
at runtime with `entity=<post urn>`, in addition to the summary rows here.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .models import Metric, MetricSet

# (category, default source_section, [metric names])
CATALOG: List[Tuple[str, str, List[str]]] = [
    ("Overview", "Page Analytics > Overview", [
        "Search Appearances",
        "New Followers",
        "Post Impressions",
        "Page Visitors",
    ]),
    ("Content", "Page Analytics > Content", [
        "Impressions",
        "Reactions",
        "Comments",
        "Reposts",
    ]),
    ("Visitors", "Page Analytics > Visitors", [
        "Page Views",
        "Unique Visitors",
        "Custom Button Clicks",
    ]),
    ("Visitors > Demographics", "Page Analytics > Visitors > Visitor demographics", [
        "Job Function",
        "Company Size",
        "Industry",
        "Location",
        "Seniority",
    ]),
    ("Life Page", "Page Analytics > Visitors > Page views by page", [
        "Page Views",
        "Unique Visitors",
        "Last Updated",
    ]),
    ("Followers", "Page Analytics > Followers", [
        "Total Followers",
        "New Followers",
    ]),
    ("Search Appearance", "Page Analytics > Search appearances", [
        "Page Searches",
        "Top Keywords",
        "Top Page Searcher Demographics",
    ]),
    ("Individual Post Analytics", "Page Analytics > Content > Post analytics", [
        "Impressions",
        "Members Reached",
        "Page Viewers from This Post",
        "Followers Gained from This Post",
        "Engagement",
        "Engagement Rate",
        "Clicks",
        "Click Through Rate",
        "Reactions",
        "Comments",
        "Reposts",
    ]),
    ("Video Posts", "Page Analytics > Content > Post analytics (video)", [
        "Video Views",
        "Watch Time",
        "Average Watch Time",
    ]),
]

# Which run-section owns which catalog categories (used for failure attribution).
SECTION_CATEGORIES: Dict[str, List[str]] = {
    "overview": ["Overview"],
    "content": ["Content"],
    "visitors": ["Visitors"],          # prefix-matches "Visitors > Demographics" too
    "life_page": ["Life Page"],
    "followers": ["Followers"],
    "search_appearances": ["Search Appearance"],
    "posts": ["Individual Post Analytics", "Video Posts"],
}

# On-page label synonyms LinkedIn has used for each catalog metric.
# Order matters: earlier labels are tried first.
LABELS: Dict[Tuple[str, str], List[str]] = {
    ("Overview", "Search Appearances"): ["Search appearances", "Search appearance"],
    ("Overview", "New Followers"): [
        "New followers in the last 30 days", "New followers", "Followers gained",
    ],
    ("Overview", "Post Impressions"): ["Post impressions", "Impressions"],
    ("Overview", "Page Visitors"): ["Page visitors", "Unique visitors", "Page views"],

    ("Content", "Impressions"): ["Impressions", "Total impressions"],
    ("Content", "Reactions"): ["Reactions", "Total reactions"],
    ("Content", "Comments"): ["Comments", "Total comments"],
    ("Content", "Reposts"): ["Reposts", "Shares", "Total reposts"],

    ("Visitors", "Page Views"): ["Page views", "Total page views"],
    ("Visitors", "Unique Visitors"): ["Unique visitors", "Total unique visitors"],
    ("Visitors", "Custom Button Clicks"): [
        "Custom button clicks", "Custom button", "Button clicks",
    ],

    ("Followers", "Total Followers"): ["Total followers", "All followers", "Followers"],
    ("Followers", "New Followers"): [
        "New followers in the last 30 days", "New followers in the past 30 days",
        "New followers", "Followers gained",
    ],

    ("Search Appearance", "Page Searches"): [
        "Page searches", "Search appearances", "Times your page appeared in search",
    ],

    ("Individual Post Analytics", "Impressions"): ["Impressions"],
    ("Individual Post Analytics", "Members Reached"): [
        "Members reached", "Unique views", "Unique members reached",
    ],
    ("Individual Post Analytics", "Page Viewers from This Post"): [
        "Page viewers from this post", "Page views from this post",
        "Page visitors from this post", "Page viewers",
    ],
    ("Individual Post Analytics", "Followers Gained from This Post"): [
        "Followers gained from this post", "New followers from this post",
        "Followers gained",
    ],
    ("Individual Post Analytics", "Engagement"): [
        "Engagements", "Engagement", "Total engagements",
    ],
    ("Individual Post Analytics", "Engagement Rate"): [
        "Engagement rate", "Engagements rate",
    ],
    ("Individual Post Analytics", "Clicks"): ["Clicks", "Total clicks"],
    ("Individual Post Analytics", "Click Through Rate"): [
        "Click through rate", "Click-through rate", "CTR",
    ],
    ("Individual Post Analytics", "Reactions"): ["Reactions"],
    ("Individual Post Analytics", "Comments"): ["Comments"],
    ("Individual Post Analytics", "Reposts"): ["Reposts", "Shares"],

    ("Video Posts", "Video Views"): [
        "Video views", "Views", "Viewers",
    ],
    ("Video Posts", "Watch Time"): [
        "Watch time", "Minutes viewed", "Total watch time", "Watch time (hours)",
    ],
    ("Video Posts", "Average Watch Time"): [
        "Average watch time", "Avg. watch time", "Average watch time per viewer",
    ],
}

# Panel -> Breakdown taxonomy exactly as named in LinkedIn's UI / the spec
# sheet: (category, metric) -> (panel, breakdown label).
PANELS: Dict[Tuple[str, str], Tuple[str, str]] = {
    # ---------------- Overview ----------------
    ("Overview", "Search Appearances"): ("Track Performance", "Search Appearances"),
    ("Overview", "New Followers"): ("Track Performance", "New Followers"),
    ("Overview", "Post Impressions"): ("Track Performance", "Post Impressions"),
    ("Overview", "Page Visitors"): ("Track Performance", "Page Visitors"),

    ("Content", "Impressions"): ("Highlights & Metrics", "Impressions"),
    ("Content", "Reactions"): ("Highlights & Metrics", "Reactions"),
    ("Content", "Comments"): ("Highlights & Metrics", "Comments"),
    ("Content", "Reposts"): ("Highlights & Metrics", "Reposts"),

    ("Visitors", "Page Views"): ("Visitor Highlights & Metrics", "Page Views"),
    ("Visitors", "Unique Visitors"): ("Visitor Highlights & Metrics", "Unique Visitors"),
    ("Visitors", "Custom Button Clicks"): ("Visitor Highlights & Metrics",
                                           "Custom Button Clicks"),

    ("Visitors > Demographics", "Job Function"): ("Visitor Demographics", "Job Function"),
    ("Visitors > Demographics", "Company Size"): ("Visitor Demographics", "Company Size"),
    ("Visitors > Demographics", "Industry"): ("Visitor Demographics", "Industry"),
    ("Visitors > Demographics", "Location"): ("Visitor Demographics", "Location"),
    ("Visitors > Demographics", "Seniority"): ("Visitor Demographics", "Seniority"),

    ("Life Page", "Page Views"): ("Life Page Traffic", "Page Views"),
    ("Life Page", "Unique Visitors"): ("Life Page Traffic", "Unique Visitors"),
    ("Life Page", "Last Updated"): ("Life Page Traffic", "Last Updated"),

    ("Followers", "Total Followers"): ("Highlights & Metrics", "Total Followers"),
    ("Followers", "New Followers"): ("Highlights & Metrics", "New Followers"),

    ("Search Appearance", "Page Searches"): ("Search Appearance Highlights",
                                             "Page Searches"),
    ("Search Appearance", "Top Keywords"): ("Search Discovery",
                                            "Top Keywords to find your page"),
    ("Search Appearance", "Top Page Searcher Demographics"): (
        "Search Discovery", "Top Page searcher demographics"),

    # ------------- Individual Post -------------
    ("Individual Post Analytics", "Impressions"): ("Organic Discovery", "Impressions"),
    ("Individual Post Analytics", "Members Reached"): ("Organic Discovery",
                                                       "Members Reached"),
    ("Individual Post Analytics", "Page Viewers from This Post"): (
        "Organic Page Activity", "Page viewers from this post"),
    ("Individual Post Analytics", "Followers Gained from This Post"): (
        "Organic Page Activity", "Followers gained from this post"),
    ("Individual Post Analytics", "Engagement"): ("Post Performance/Engagement",
                                                  "Engagement"),
    ("Individual Post Analytics", "Engagement Rate"): ("Post Performance/Engagement",
                                                       "Engagement Rate"),
    ("Individual Post Analytics", "Clicks"): ("Post Performance/Engagement", "Clicks"),
    ("Individual Post Analytics", "Click Through Rate"): ("Post Performance/Engagement",
                                                          "Click Through Rate"),
    ("Individual Post Analytics", "Reactions"): ("Post Performance/Engagement",
                                                 "Reactions"),
    ("Individual Post Analytics", "Comments"): ("Post Performance/Engagement", "Comments"),
    ("Individual Post Analytics", "Reposts"): ("Post Performance/Engagement", "Reposts"),

    ("Video Posts", "Video Views"): ("Video Performance", "Videos Views"),
    ("Video Posts", "Watch Time"): ("Video Performance", "Watch Time"),
    ("Video Posts", "Average Watch Time"): ("Video Performance", "Average Watch Time"),
}


def panel_for(category: str, metric_name: str) -> Tuple[str, str]:
    """(panel, breakdown label) for a metric; falls back to the category/name."""
    return PANELS.get((category, metric_name), (category, metric_name))


# Metrics that ARE percentages, so a "%" token is the value rather than a
# period-over-period change indicator.
RATE_METRICS = {
    ("Individual Post Analytics", "Engagement Rate"),
    ("Individual Post Analytics", "Click Through Rate"),
}


def allows_percent(category: str, metric_name: str) -> bool:
    return (category, metric_name) in RATE_METRICS


# Demographic dropdown option labels on the Visitors page.
DEMOGRAPHIC_OPTIONS: Dict[str, List[str]] = {
    "Job Function": ["Job function", "Job functions", "Function"],
    "Company Size": ["Company size", "Company sizes"],
    "Industry": ["Industry", "Industries"],
    "Location": ["Location", "Locations"],
    "Seniority": ["Seniority", "Seniority level"],
}


def build_metric_set() -> MetricSet:
    """Pre-register every requested metric as not-yet-extracted."""
    ms = MetricSet()
    for category, section, names in CATALOG:
        for name in names:
            panel, breakdown = panel_for(category, name)
            ms.register(Metric(metric_name=name, category=category,
                               source_section=section, requested=True,
                               panel=panel, breakdown=breakdown))
    return ms


def labels_for(category: str, metric_name: str) -> List[str]:
    return LABELS.get((category, metric_name), [metric_name])
