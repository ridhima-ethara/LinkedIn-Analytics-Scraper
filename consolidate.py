#!/usr/bin/env python3
"""Build a hand-off folder from an extraction run, laid out as LinkedIn's own
panels: "LinkedIn Panel" -> "Breakdown" -> value, for the page overall and for
each individual post.

Usage
-----
  python consolidate.py                                   # newest run
  python consolidate.py --run overall --out output/DELIVERABLE_overall
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"

OVERALL_PANEL_ORDER = [
    "Track Performance", "Highlights & Metrics", "Visitor Highlights & Metrics",
    "Visitor Demographics", "Life Page Traffic", "Search Appearance Highlights",
    "Search Discovery",
]
POST_PANEL_ORDER = [
    "Organic Discovery", "Organic Page Activity", "Post Performance/Engagement",
    "Video Performance",
]

OVERALL_FIELDS = ["LinkedIn Panel", "Breakdown", "Bucket", "Value", "Share", "Unit",
                  "Date Range", "Status", "Limitation", "Source Section", "Reason",
                  "Evidence"]
POST_FIELDS = ["Post", "Post Type", "Post Date", "Post URN", "LinkedIn Panel",
               "Breakdown", "Value", "Unit", "Status", "Date Range", "Reason"]
BUCKET_FIELDS = ["LinkedIn Panel", "Breakdown", "Bucket", "Visitors", "Share",
                 "Date Range", "Status"]


def newest_run() -> Path:
    runs = [d for d in OUTPUT.iterdir() if d.is_dir() and (d / "analytics.json").exists()]
    if not runs:
        raise SystemExit("no completed run found under output/")
    return max(runs, key=lambda d: (d / "analytics.json").stat().st_mtime)


def jvalue(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v


def all_metrics(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ((data.get("metrics") or [])
            + (data.get("additional_metrics_discovered") or [])
            + (data.get("metric_breakdown_rows") or []))


def order_key(panel: str, order: List[str]) -> int:
    return order.index(panel) if panel in order else len(order)


def _visitors(value: Any) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", str(value)) or 0)
    except ValueError:
        return 0.0


def overall_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Page-level panels: one row per Breakdown, in LinkedIn's panel order.

    Visitor Demographics breakdowns are expanded in place: the dimension row is
    followed by one row per bucket carrying the bucket NAME, its visitor count
    and its share, so the names/percentages live in this file too.
    """
    buckets_by_dim: Dict[str, List[Dict[str, Any]]] = {}
    for m in all_metrics(data):
        if m.get("entity") and "Demographics" in m.get("category", ""):
            dim = m.get("breakdown") or m.get("metric_name", "")
            buckets_by_dim.setdefault(dim, []).append(m)
    for dim in buckets_by_dim:
        buckets_by_dim[dim].sort(key=lambda b: -_visitors(b.get("value")))

    rows = []
    for m in all_metrics(data):
        if m.get("entity"):
            continue
        panel = m.get("panel") or m.get("category", "")
        if panel in POST_PANEL_ORDER:
            continue
        breakdown = m.get("breakdown") or m.get("metric_name", "")
        sort_key = (order_key(panel, OVERALL_PANEL_ORDER), breakdown, 0)
        rows.append({
            "LinkedIn Panel": panel,
            "Breakdown": breakdown,
            "Bucket": "",
            "Value": jvalue(m.get("value")),
            "Share": "",
            "Unit": m.get("unit", ""),
            "Date Range": m.get("date_range", ""),
            "Status": m.get("status", ""),
            "Limitation": m.get("limitation", ""),
            "Source Section": m.get("source_section", ""),
            "Reason": m.get("reason", ""),
            "Evidence": (m.get("evidence") or "")[:160],
            "_sort": sort_key,
        })
        for i, b in enumerate(buckets_by_dim.get(breakdown, []), start=1):
            if panel != "Visitor Demographics":
                break
            detail = b.get("detail") or {}
            rows.append({
                "LinkedIn Panel": panel,
                "Breakdown": breakdown,
                "Bucket": b.get("entity", ""),
                "Value": jvalue(b.get("value")),
                "Share": detail.get("share_percent", ""),
                "Unit": b.get("unit", "") or "visitors",
                "Date Range": b.get("date_range", ""),
                "Status": b.get("status", ""),
                "Limitation": b.get("limitation", ""),
                "Source Section": b.get("source_section", ""),
                "Reason": b.get("reason", ""),
                "Evidence": (b.get("evidence") or "")[:160],
                "_sort": (sort_key[0], breakdown, i),
            })
    rows.sort(key=lambda r: r.pop("_sort"))
    return rows


def bucket_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Visitor-demographic buckets: Breakdown -> bucket -> visitors + share."""
    rows = []
    for m in all_metrics(data):
        if not m.get("entity") or "Demographics" not in m.get("category", ""):
            continue
        detail = m.get("detail") or {}
        rows.append({
            "LinkedIn Panel": m.get("panel") or "Visitor Demographics",
            "Breakdown": m.get("breakdown") or m.get("metric_name", ""),
            "Bucket": m.get("entity", ""),
            "Visitors": jvalue(m.get("value")),
            "Share": detail.get("share_percent", ""),
            "Date Range": m.get("date_range", ""),
            "Status": m.get("status", ""),
        })
    rows.sort(key=lambda r: (r["Breakdown"], -(float(re.sub(r"[^\d.]", "", str(r["Visitors"])) or 0))))
    return rows


def post_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-post analytics in the Individual Post panel layout."""
    posts = {p.get("urn"): p for p in (data.get("posts") or []) if p.get("urn")}
    rows = []
    for m in all_metrics(data):
        urn = m.get("entity", "")
        if not urn.startswith("urn:li:"):
            continue
        panel = m.get("panel") or m.get("category", "")
        if panel not in POST_PANEL_ORDER:
            continue
        post = posts.get(urn, {})
        rows.append({
            "Post": (post.get("title") or "")[:90],
            "Post Type": post.get("post_type", ""),
            "Post Date": post.get("date", ""),
            "Post URN": urn,
            "LinkedIn Panel": panel,
            "Breakdown": m.get("breakdown") or m.get("metric_name", ""),
            "Value": jvalue(m.get("value")),
            "Unit": m.get("unit", ""),
            "Status": m.get("status", ""),
            "Date Range": m.get("date_range", ""),
            "Reason": m.get("reason", ""),
            "_sort": (urn, order_key(panel, POST_PANEL_ORDER)),
        })
    rows.sort(key=lambda r: r.pop("_sort"))
    return rows


def write_csv(path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def run_history() -> List[Dict[str, Any]]:
    out = []
    for d in sorted(OUTPUT.iterdir()):
        meta = d / "analytics.json"
        if not d.is_dir() or not meta.exists():
            continue
        data = json.loads(meta.read_text())
        s, run = data.get("summary", {}), data.get("run", {})
        out.append({
            "run_folder": d.name, "page": run.get("company_url", ""),
            "started_at": run.get("started_at", ""),
            "date_range_applied": data.get("date_range_applied", ""),
            "extracted": s.get("extracted"), "partial": s.get("partially_extracted"),
            "not_accessible": s.get("not_accessible"),
        })
    return out


README = """# LinkedIn Page Analytics — {page}

**Date range reported by LinkedIn:** {date_range}
**Run:** `{run_folder}` · {started} · posts analysed: **{n_posts}**

Laid out exactly as the LinkedIn panels: *LinkedIn Panel* → *Breakdown* → value.
Every value was read from the rendered admin UI while signed in as a Page admin.
Nothing is estimated or inferred; anything not captured carries a reason.

## Overall page analytics

| File | Contents |
|---|---|
| `OVERALL_ANALYTICS.csv` | every page-level Breakdown, grouped by panel ({n_overall} rows). Visitor Demographics rows are expanded inline: the dimension row (value = number of buckets LinkedIn renders) is followed by one row per bucket with `Bucket`, `Value` (visitors) and `Share` (%). |
| `VISITOR_DEMOGRAPHICS.csv` | each demographic Breakdown split into buckets with visitors + share ({n_buckets} rows) |

Panels: Track Performance · Highlights & Metrics · Visitor Highlights & Metrics ·
Visitor Demographics · Life Page Traffic · Search Appearance Highlights · Search Discovery

## Post-wise analytics

| File | Contents |
|---|---|
| `POST_ANALYTICS.csv` | long format: one row per post × Breakdown ({n_post_rows} rows) |
| `POST_ANALYTICS_WIDE.csv` | one row per post, one column per metric |
| `posts/<n>_<urn>.csv` | a separate per-post sheet, Panel → Breakdown → Value |

Panels: Organic Discovery · Organic Page Activity · Post Performance/Engagement ·
Video Performance

## Also included

`analytics.json` (full machine-readable output incl. evidence) · `run_meta.json` ·
`unavailable_metrics_report.md` · `unavailable.csv` · `run_history.csv` ·
`screenshots/`

## Caveats that affect how you read these numbers

- **Post metrics are lifetime.** LinkedIn reports each post cumulatively since it
  was published and does not filter post analytics by date range.
- **Video Performance appears only for video posts.** For other post types those
  three rows are marked `not_accessible` with limitation `data_unavailable`,
  because LinkedIn does not report them.
- **Search Discovery rows are label-only.** LinkedIn lists the top keywords and
  top searcher companies with **no counts**, so they are `partial`.
- **Track Performance cards use their own period** (LinkedIn fixes them to
  `last 7 days`), which differs from the page date filter. Check each row's
  `Date Range`.
- LinkedIn's Page analytics support a **365-day maximum** window; there is no
  all-time view for these metrics (Total Followers is a live lifetime figure).
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a panel-structured hand-off folder")
    ap.add_argument("--run", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    run = (OUTPUT / args.run) if args.run else newest_run()
    if not (run / "analytics.json").exists():
        raise SystemExit(f"{run} has no analytics.json (did the run finish?)")
    data = json.loads((run / "analytics.json").read_text())
    dest = Path(args.out) if args.out else OUTPUT / f"DELIVERABLE_{run.name}"
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.mkdir(parents=True, exist_ok=True)

    ov = overall_rows(data)
    bk = bucket_rows(data)
    pr = post_rows(data)
    n_overall = write_csv(dest / "OVERALL_ANALYTICS.csv", ov, OVERALL_FIELDS)
    n_buckets = write_csv(dest / "VISITOR_DEMOGRAPHICS.csv", bk, BUCKET_FIELDS)
    n_post_rows = write_csv(dest / "POST_ANALYTICS.csv", pr, POST_FIELDS)
    write_csv(dest / "unavailable.csv",
              [r for r in ov if r["Status"] != "extracted"]
              + [{k: r.get(k, "") for k in OVERALL_FIELDS}
                 for r in pr if r["Status"] != "extracted"], OVERALL_FIELDS)
    write_csv(dest / "run_history.csv", run_history(),
              ["run_folder", "page", "started_at", "date_range_applied",
               "extracted", "partial", "not_accessible"])

    # one sheet per post + a wide table
    posts = [p for p in (data.get("posts") or []) if p.get("urn")]
    wide: List[Dict[str, Any]] = []
    for i, post in enumerate(posts, start=1):
        urn = post["urn"]
        mine = [r for r in pr if r["Post URN"] == urn]
        if mine:
            write_csv(dest / "posts" / f"{i:02d}_{urn.split(':')[-1]}.csv",
                      mine, POST_FIELDS)
        row = {"#": i, "Post": (post.get("title") or "")[:90],
               "Post Type": post.get("post_type", ""), "Post Date": post.get("date", ""),
               "Post URN": urn, "Analytics URL": post.get("detail_url", "")}
        for r in mine:
            row[f"{r['LinkedIn Panel']} — {r['Breakdown']}"] = r["Value"]
        wide.append(row)
    if wide:
        cols: List[str] = []
        for r in wide:
            for k in r:
                if k not in cols:
                    cols.append(k)
        write_csv(dest / "POST_ANALYTICS_WIDE.csv", wide, cols)

    for name in ("analytics.json", "run_meta.json", "unavailable_metrics_report.md",
                 "unavailable_metrics_report.json", "metrics.csv"):
        if (run / name).exists():
            shutil.copy2(run / name, dest / name)
    if (run / "screenshots").exists():
        shutil.copytree(run / "screenshots", dest / "screenshots", dirs_exist_ok=True)

    meta = data.get("run", {})
    ranges = [r["Date Range"] for r in ov if r["Status"] == "extracted" and r["Date Range"]]
    main_range = max(set(ranges), key=ranges.count) if ranges else data.get(
        "date_range_applied", "unknown")
    (dest / "README.md").write_text(README.format(
        page=meta.get("company_url", ""), date_range=main_range, run_folder=run.name,
        started=meta.get("started_at", ""), n_posts=len(posts), n_overall=n_overall,
        n_buckets=n_buckets, n_post_rows=n_post_rows), encoding="utf-8")

    print(f"deliverable -> {dest}")
    print(f"  OVERALL_ANALYTICS.csv    : {n_overall} rows "
          f"({sum(1 for r in ov if r['Bucket'])} demographic bucket rows inline)")
    print(f"  VISITOR_DEMOGRAPHICS.csv : {n_buckets} rows")
    print(f"  POST_ANALYTICS.csv       : {n_post_rows} rows across {len(posts)} post(s)")
    print(f"  posts/                   : {len(posts)} per-post sheet(s)")
    print(f"  date range               : {main_range}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
