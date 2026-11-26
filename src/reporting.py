"""Report writers: metrics JSON/CSV, posts CSV, and the Unavailable Metrics Report."""
from __future__ import annotations

import csv
import json
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List

from .logging_setup import get_logger
from .models import Limitation, Metric, Status
from .sections.base import RunContext

log = get_logger("report")

METRIC_FIELDS = [
    "panel", "breakdown", "metric_name", "value", "raw_value", "unit", "date_range", "category", "status",
    "source_section", "source_url", "entity", "limitation", "reason", "strategy",
    "evidence", "extracted_at",
]

POST_FIELDS = [
    "urn", "title", "post_type", "date", "created_by", "is_video", "detail_status",
    "detail_url",
    "list_impressions", "list_reactions", "list_comments", "list_reposts",
    "list_engagement_rate", "list_clicks",
    "detail_Impressions", "detail_Members Reached", "detail_Page Viewers from This Post",
    "detail_Followers Gained from This Post", "detail_Engagement", "detail_Engagement Rate",
    "detail_Clicks", "detail_Click Through Rate", "detail_Reactions", "detail_Comments",
    "detail_Reposts", "detail_Video Views", "detail_Watch Time", "detail_Average Watch Time",
    "source_url",
]

LIMITATION_EXPLAINED = {
    Limitation.NONE: "No limitation — value captured from the live page.",
    Limitation.LINKEDIN_UI:
        "LinkedIn UI limitation: the metric is not rendered in the accessible admin "
        "interface (or LinkedIn changed/removed that element).",
    Limitation.PERMISSIONS:
        "Permissions limitation: the signed-in account's role on this Page does not "
        "grant access to that section.",
    Limitation.DATA_UNAVAILABLE:
        "Data unavailable: the section loaded but LinkedIn itself reports no data for "
        "the selected date range / post type.",
    Limitation.AUTOMATION_FAILURE:
        "Automation failure: navigation or parsing in this script failed — re-runnable.",
    Limitation.SESSION_EXPIRED:
        "Session limitation: the authenticated LinkedIn session expired or was "
        "challenged mid-run; re-authenticate with login.py and re-run.",
    Limitation.NOT_ATTEMPTED:
        "Not attempted: the section was disabled or never reached in this run.",
}


def _metric_row(m: Metric) -> Dict[str, Any]:
    d = m.as_dict()
    value = d.get("value")
    if isinstance(value, (list, dict)):
        value = json.dumps(value, default=str)
    return {f: (value if f == "value" else d.get(f, "")) for f in METRIC_FIELDS}


def write_reports(ctx: RunContext, run_meta: Dict[str, Any]) -> Dict[str, str]:
    out = ctx.out_dir
    out.mkdir(parents=True, exist_ok=True)
    metrics = ctx.metrics.all()
    catalog_rows = [m for m in metrics if m.requested]
    extra_rows = [m for m in metrics if not m.requested and not m.entity]
    entity_rows = [m for m in metrics if not m.requested and m.entity]

    summary = _summarise(metrics, catalog_rows, extra_rows, entity_rows)
    files: Dict[str, str] = {}

    # ---------------------------------------------------------------- JSON
    payload = {
        "run": run_meta,
        "summary": summary,
        "date_range_applied": ctx.date_range,
        "date_range_requested": ctx.requested_range,
        "date_window_requested": (f"{ctx.date_window[0]} .. {ctx.date_window[1]}"
                                  if ctx.date_window else None),
        "date_range_verified": ctx.date_range_verified,
        "date_range_verification": ctx.date_range_explanation,
        "sections": ctx.section_status,
        "notes": ctx.notes,
        "discovered_analytics_nav": ctx.nav_map,
        "metrics": [m.as_dict() for m in catalog_rows],
        "additional_metrics_discovered": [m.as_dict() for m in extra_rows],
        "metric_breakdown_rows": [m.as_dict() for m in entity_rows],
        "posts": ctx.posts,
        "screenshots": ctx.screenshots,
    }
    p = out / "analytics.json"
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    files["analytics_json"] = str(p)

    # ----------------------------------------------------------- metrics CSV
    p = out / "metrics.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=METRIC_FIELDS)
        w.writeheader()
        for m in metrics:
            w.writerow(_metric_row(m))
    files["metrics_csv"] = str(p)

    # ------------------------------------------------------------- posts CSV
    p = out / "posts.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=POST_FIELDS, extrasaction="ignore")
        w.writeheader()
        for post in ctx.posts:
            w.writerow({k: post.get(k, "") for k in POST_FIELDS})
    files["posts_csv"] = str(p)

    # ------------------------------------------- unavailable metrics report
    report = _unavailable_report(ctx, run_meta, summary, catalog_rows, extra_rows,
                                 entity_rows)
    p = out / "unavailable_metrics_report.json"
    p.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    files["unavailable_json"] = str(p)

    p = out / "unavailable_metrics_report.md"
    p.write_text(_render_markdown(report), encoding="utf-8")
    files["unavailable_md"] = str(p)

    log.info("reports written to %s", out)
    return files


def _summarise(all_metrics: List[Metric], catalog_rows: List[Metric],
               extra_rows: List[Metric], entity_rows: List[Metric]) -> Dict[str, Any]:
    by_status = Counter(m.status for m in catalog_rows)
    by_limitation = Counter(m.limitation for m in catalog_rows
                            if m.status != Status.EXTRACTED)
    by_category: Dict[str, Dict[str, int]] = OrderedDict()
    for m in catalog_rows:
        bucket = by_category.setdefault(m.category, {Status.EXTRACTED: 0, Status.PARTIAL: 0,
                                                     Status.NOT_ACCESSIBLE: 0})
        bucket[m.status] += 1
    blocked_by = None
    not_ok = [m for m in catalog_rows if m.status != Status.EXTRACTED]
    if catalog_rows and len(not_ok) == len(catalog_rows):
        limits = {m.limitation for m in not_ok}
        if limits == {Limitation.SESSION_EXPIRED}:
            blocked_by = ("authentication — no valid LinkedIn session, so no analytics page "
                          "was ever opened. Nothing was extracted. Run `python login.py` "
                          "(human login + MFA), then re-run.")
        elif limits == {Limitation.PERMISSIONS}:
            blocked_by = ("permissions — the signed-in account cannot open this Page's admin "
                          "analytics. Confirm it is an admin of the Page.")
    return {
        "blocked_by": blocked_by,
        "requested_metrics": len(catalog_rows),
        "extracted": by_status.get(Status.EXTRACTED, 0),
        "partially_extracted": by_status.get(Status.PARTIAL, 0),
        "not_accessible": by_status.get(Status.NOT_ACCESSIBLE, 0),
        "additional_metrics_discovered": len(extra_rows),
        "additional_breakdown_rows": len(entity_rows),
        "by_limitation": dict(by_limitation),
        "by_category": by_category,
    }


def _brief(m: Metric) -> Dict[str, Any]:
    return {
        "metric": m.metric_name,
        "category": m.category,
        "value": m.value,
        "raw_value": m.raw_value,
        "unit": m.unit,
        "date_range": m.date_range,
        "source_section": m.source_section,
        "source_url": m.source_url,
        "evidence": m.evidence,
        "strategy": m.strategy,
    }


def _problem(m: Metric) -> Dict[str, Any]:
    d = _brief(m)
    d.update({
        "status": m.status,
        "reason": m.reason,
        "limitation_type": m.limitation,
        "limitation_explained": LIMITATION_EXPLAINED.get(m.limitation, ""),
    })
    return d


def _unavailable_report(ctx: RunContext, run_meta: Dict[str, Any], summary: Dict[str, Any],
                        catalog_rows: List[Metric], extra_rows: List[Metric],
                        entity_rows: List[Metric]) -> Dict[str, Any]:
    return {
        "run": run_meta,
        "summary": summary,
        "date_range_applied": ctx.date_range,
        "date_window_requested": (f"{ctx.date_window[0]} .. {ctx.date_window[1]}"
                                  if ctx.date_window else None),
        "date_range_verified": ctx.date_range_verified,
        "date_range_verification": ctx.date_range_explanation,
        "sections": ctx.section_status,
        "notes": ctx.notes,
        "successfully_extracted": [_brief(m) for m in catalog_rows
                                   if m.status == Status.EXTRACTED],
        "partially_extracted": [_problem(m) for m in catalog_rows
                                if m.status == Status.PARTIAL],
        "not_accessible": [_problem(m) for m in catalog_rows
                           if m.status == Status.NOT_ACCESSIBLE],
        "additional_metrics_discovered": [_brief(m) for m in extra_rows
                                         if m.status == Status.EXTRACTED],
        "breakdown_rows_extracted": [_brief(m) for m in entity_rows
                                     if m.status == Status.EXTRACTED],
        "breakdown_rows_unavailable": [_problem(m) for m in entity_rows
                                       if m.status != Status.EXTRACTED],
        "limitation_legend": LIMITATION_EXPLAINED,
    }


def _md_table(rows: List[List[str]], headers: List[str]) -> str:
    if not rows:
        return "_none_\n"
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _render_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    run = report["run"]
    out: List[str] = []
    out.append("# LinkedIn Page Analytics — Extracted vs Unavailable Report\n")
    if s.get("blocked_by"):
        out.append(f"> ## NO ANALYTICS WERE EXTRACTED\n>\n> **Blocked by {s['blocked_by']}**\n>\n"
                   f"> Every metric below is `not_accessible` for that one reason — this is "
                   f"not a per-metric finding about your Page.\n")
    out.append(f"- **Page:** {run.get('company_url')}")
    out.append(f"- **Run id:** {run.get('run_id')}")
    out.append(f"- **Started (UTC):** {run.get('started_at')}")
    out.append(f"- **Finished (UTC):** {run.get('finished_at')}")
    out.append(f"- **Date range applied (read back from LinkedIn):** "
               f"{report.get('date_range_applied')}")
    if report.get("date_window_requested"):
        verified = report.get("date_range_verified")
        mark = {True: "VERIFIED", False: "NOT VERIFIED", None: "not checked"}[verified]
        out.append(f"- **Date window requested:** {report['date_window_requested']} "
                   f"— **{mark}**")
        if report.get("date_range_verification"):
            out.append(f"- **Window check:** {report['date_range_verification']}")
    out.append(f"- **Authenticated session:** {run.get('session_state')}")
    out.append(f"- **Browser:** Playwright {run.get('playwright_version', '')} / "
               f"Firefox (headless={run.get('headless')})\n")

    out.append("## Summary\n")
    out.append(_md_table(
        [[s["requested_metrics"], s["extracted"], s["partially_extracted"],
          s["not_accessible"], s["additional_breakdown_rows"]]],
        ["Requested metrics", "Extracted", "Partial", "Not accessible",
         "Extra breakdown rows"]))

    out.append("\n### By category\n")
    out.append(_md_table(
        [[cat, v[Status.EXTRACTED], v[Status.PARTIAL], v[Status.NOT_ACCESSIBLE]]
         for cat, v in s["by_category"].items()],
        ["Category", "Extracted", "Partial", "Not accessible"]))

    if s["by_limitation"]:
        out.append("\n### Reasons for incomplete metrics\n")
        out.append(_md_table([[k, v, LIMITATION_EXPLAINED.get(k, "")]
                              for k, v in s["by_limitation"].items()],
                             ["Limitation", "Count", "Meaning"]))

    out.append("\n## 1. Successfully extracted\n")
    out.append(_md_table(
        [[m["category"], m["metric"], m["value"], m["unit"], m["date_range"],
          m["source_section"]] for m in report["successfully_extracted"]],
        ["Category", "Metric", "Value", "Unit", "Date range", "Source section"]))

    out.append("\n## 2. Partially extracted\n")
    out.append(_md_table(
        [[m["category"], m["metric"], m["value"], m["limitation_type"], m["reason"]]
         for m in report["partially_extracted"]],
        ["Category", "Metric", "Captured", "Limitation", "Reason"]))

    out.append("\n## 3. Not accessible\n")
    out.append(_md_table(
        [[m["category"], m["metric"], m["limitation_type"], m["reason"],
          m["source_url"] or "-"] for m in report["not_accessible"]],
        ["Category", "Metric", "Limitation", "Exact reason", "Source URL"]))

    sections = report.get("sections") or {}
    if sections:
        out.append("\n## Section navigation outcomes\n")
        out.append(_md_table(
            [[k, v.get("outcome"), v.get("url") or "-", v.get("reason") or "-"]
             for k, v in sections.items()],
            ["Section", "Outcome", "URL", "Reason"]))

    if report.get("notes"):
        out.append("\n## Run notes\n")
        for n in report["notes"]:
            out.append(f"- {n}")
        out.append("")

    out.append("\n## Limitation legend\n")
    for k, v in report["limitation_legend"].items():
        out.append(f"- **{k}** — {v}")
    out.append("\n---\n_No value in this report is estimated, inferred or "
               "back-filled: every number was read from the rendered LinkedIn page, and "
               "anything that could not be read is listed above with its reason._\n")
    return "\n".join(out)


def print_console_summary(ctx: RunContext, files: Dict[str, str]) -> None:
    metrics = [m for m in ctx.metrics.all() if m.requested]
    counts = Counter(m.status for m in metrics)
    print("\n=== Extraction summary ===")
    print(f"requested metrics : {len(metrics)}")
    print(f"extracted         : {counts.get(Status.EXTRACTED, 0)}")
    print(f"partial           : {counts.get(Status.PARTIAL, 0)}")
    print(f"not accessible    : {counts.get(Status.NOT_ACCESSIBLE, 0)}")
    print(f"date range        : {ctx.date_range}")
    if ctx.date_window:
        print(f"window requested  : {ctx.date_window[0]} .. {ctx.date_window[1]} "
              f"(verified={ctx.date_range_verified})")
    for name, path in files.items():
        print(f"{name:16s}: {path}")
