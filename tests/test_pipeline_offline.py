"""End-to-end pipeline test against local HTML fixtures.

Runs every section, the date-filter logic, pagination, post-detail navigation and
all report writers without touching LinkedIn or any credentials. Output goes to
output/offline-fixture-run/ and doubles as the format sample for the deliverable.

Run:  .venv/bin/python tests/test_pipeline_offline.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import dates  # noqa: E402
from src.browser import launch  # noqa: E402
from src.catalog import build_metric_set  # noqa: E402
from src.config import load_config  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.models import Status  # noqa: E402
from src.reporting import print_console_summary, write_reports  # noqa: E402
from src.sections import ORDER, RunContext  # noqa: E402

FIXTURES = Path(__file__).resolve().parent
ANALYTICS = (FIXTURES / "fixture_analytics.html").as_uri()
POST = (FIXTURES / "fixture_post.html").as_uri()
RUN_ID = "offline-fixture-run"


def main() -> int:
    overrides = {
        "urls": {
            "overview": ANALYTICS, "content": ANALYTICS, "visitors": ANALYTICS,
            "followers": ANALYTICS, "search_appearances": ANALYTICS,
            "life_page": ANALYTICS, "post_summary_templates": [POST],
        },
        "extraction": {
            "date_range": "year_2026", "max_posts": 2, "post_detail": True,
            "expand_show_more_rounds": 1, "settle_ms": 300, "scroll_passes": 1,
            "retries": 1, "retry_backoff_s": 0,
            "sections": [c.key for c in ORDER],
        },
        "output": {"dir": "output", "save_screenshots": True, "save_page_text": True,
                   "save_raw_network": False, "prefix": "fixture"},
    }
    cfg = load_config(None, overrides)
    setup_logging("INFO", ROOT / "logs", RUN_ID)

    out_dir = ROOT / "output" / RUN_ID
    ctx = RunContext(cfg=cfg, page=None, metrics=build_metric_set(), out_dir=out_dir,
                     run_id=RUN_ID, requested_range="year_2026",
                     date_window=dates.resolve_window({"date_range": "year_2026"}))  # type: ignore[arg-type]
    bundle = launch(cfg, headless=True, use_session=False, record_network=False)
    ctx.page = bundle.page
    try:
        for cls in ORDER:
            cls().run(ctx)
    finally:
        bundle.close()

    meta = {
        "tool_version": "offline-fixture-test", "run_id": RUN_ID,
        "company_url": "LOCAL FIXTURE (tests/fixture_analytics.html)",
        "company_id": "fixture", "headless": True,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_state": "n/a (local fixture, no LinkedIn access)",
        "browser_engine": "firefox (playwright)",
        "WARNING": "All values below come from local test fixtures, NOT from LinkedIn.",
    }
    files = write_reports(ctx, meta)
    print_console_summary(ctx, files)

    # ---- assertions on the fixture's known-correct values ---------------
    want = {
        ("Overview", "Search Appearances"): 1200,
        ("Overview", "New Followers"): 214,
        ("Overview", "Post Impressions"): 45901,
        ("Content", "Reactions"): 1004,
        ("Content", "Comments"): 87,
        ("Content", "Reposts"): 22,
        ("Visitors", "Page Views"): 7129,
        ("Visitors", "Unique Visitors"): 2045,
        ("Visitors", "Custom Button Clicks"): 38,
        ("Life Page", "Page Views"): 1220,
        ("Life Page", "Unique Visitors"): 480,
        ("Life Page", "Last Updated"): "Nov 12, 2026",
        ("Followers", "Total Followers"): 13204,
        ("Followers", "New Followers"): 214,
    }
    fails = []
    for (cat, name), expected in want.items():
        m = ctx.metrics.get(cat, name)
        got = m.value if m else None
        ok = got == expected and m and m.status == Status.EXTRACTED
        print(f"  {'PASS' if ok else 'FAIL'}  {cat} / {name}: got={got!r} want={expected!r}"
              f"{'' if ok else ' | ' + (m.reason if m else 'missing')}")
        if not ok:
            fails.append(f"{cat}/{name}")

    # per-post detail rows (entity-scoped)
    urns = [p["urn"] for p in ctx.posts if p.get("urn")]
    print(f"\n  posts listed: {len(ctx.posts)}, with urn: {len(urns)}")
    for urn in urns[:2]:
        m = ctx.metrics.get("Individual Post Analytics", "Members Reached", urn)
        ok = bool(m and m.value == 6112)
        print(f"  {'PASS' if ok else 'FAIL'}  post {urn[-4:]} members reached: "
              f"{m.value if m else None}")
        if not ok:
            fails.append(f"post/{urn}")
    vm = ctx.metrics.get("Video Posts", "Watch Time", urns[1]) if len(urns) > 1 else None
    ok = bool(vm and vm.value == "1h 23m")
    print(f"  {'PASS' if ok else 'FAIL'}  video post watch time: {vm.value if vm else None}")
    if not ok:
        fails.append("video/watch-time")

    # the requested calendar-year window must have been applied AND verified
    print(f"\n  window requested: {ctx.date_window[0]} .. {ctx.date_window[1]}")
    print(f"  label read back : {ctx.date_range}")
    ok = ctx.date_range_verified is True
    print(f"  {'PASS' if ok else 'FAIL'}  date window verified against the UI label"
          f" | {ctx.date_range_explanation}")
    if not ok:
        fails.append("date-window-verification")
    yr = all(str(ctx.metrics.get(c, n).date_range).find("2026") >= 0
             for c, n in (("Visitors", "Page Views"), ("Followers", "Total Followers")))
    print(f"  {'PASS' if yr else 'FAIL'}  metric rows carry the 2026 window as date_range")
    if not yr:
        fails.append("metric-date-range")

    # the report must be self-consistent
    report = json.loads((out_dir / "unavailable_metrics_report.json").read_text())
    s = report["summary"]
    total = s["extracted"] + s["partially_extracted"] + s["not_accessible"]
    ok = total == s["requested_metrics"]
    print(f"  {'PASS' if ok else 'FAIL'}  report accounts for every requested metric "
          f"({total}/{s['requested_metrics']})")
    if not ok:
        fails.append("report-consistency")
    for entry in report["not_accessible"]:
        if not entry["reason"] or not entry["limitation_type"]:
            fails.append(f"missing-reason/{entry['metric']}")
    print(f"  {'PASS' if not any(f.startswith('missing-reason') for f in fails) else 'FAIL'}"
          f"  every not-accessible metric carries a reason + limitation type")

    print("\n" + ("PIPELINE CHECKS PASSED" if not fails else f"FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
