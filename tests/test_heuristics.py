"""Offline validation of the extraction heuristics against local fixtures.

Run:  .venv/bin/python tests/test_heuristics.py
No LinkedIn access and no credentials are involved.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from src import dom  # noqa: E402
from src.jsfuncs import INSTALL_JS  # noqa: E402

FIXTURES = Path(__file__).resolve().parent
FAILS: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(name)


def test_parse_number() -> None:
    print("parse_number")
    cases = [("1,234", 1234), ("7,129", 7129), ("1.2K", 1200), ("3.45%", 3.45),
             ("38", 38), ("45,901", 45901), ("", None), ("—", None), (None, None),
             ("2.1M", 2100000), ("0", 0)]
    for raw, want in cases:
        check(f"parse({raw!r})", dom.parse_number(raw), want)


def test_overview(page) -> None:
    print("\nfixture_analytics.html — label -> value")
    expect = {
        "Page views": "7,129", "Unique visitors": "2,045",
        "Custom button clicks": "38", "Search appearances": "1.2K",
        "New followers": "214", "Post impressions": "45,901",
        "Total followers": "13,204", "Reactions": "1,004",
        "Comments": "87", "Reposts": "22",
    }
    for label, want in expect.items():
        hit = dom.find_metric(page, [label])
        check(label, (hit or {}).get("raw"), want)

    print("\n  tables / nav / breakdown / empty states")
    tables = dom.tables(page)
    check("table count", len(tables), 2)
    posts = [t for t in tables if "Impressions" in t["headers"]]
    check("post rows", len(posts[0]["rows"]) if posts else 0, 2)
    urns = dom.post_urns(page)
    check("urns found", len(urns), 2)
    check("urn format", urns[0].startswith("urn:li:activity:"), True)
    nav = dom.nav_links(page)
    check("nav links", len(nav), 4)
    bd = dom.breakdown(page, "Job function")
    check("breakdown rows", len((bd or {}).get("rows", [])), 3)
    check("breakdown first", ((bd or {}).get("rows") or [{}])[0].get("label"), "Engineering")
    empties = dom.empty_states(page)
    check("empty state detected",
          any("No data available" in e for e in empties), True)
    ranges = dom.date_range_labels(page)
    check("explicit date range preferred over a preset label",
          any("10/28/2026 - 11/24/2026" in r for r in ranges), True)
    check("no %-change string mistaken for a range label",
          any("%" in r for r in ranges), False)

    # Life page row isolated from the "page views by page" table
    life = [r for t in tables for r in t["rows"] if r["cells"] and r["cells"][0] == "Life page"]
    check("life page row", life[0]["cells"][1] if life else None, "1,220")


def test_post(page) -> None:
    print("\nfixture_post.html — post + video metrics")
    expect = {
        "Impressions": "8,330", "Members reached": "6,112",
        "Page viewers from this post": "142",
        "Followers gained from this post": "17",
        "Engagements": "296",
        "Clicks": "211",
        "Reactions": "260", "Comments": "18", "Reposts": "6",
        "Video views": "4,208",
    }
    for label, want in expect.items():
        hit = dom.find_metric(page, [label])
        check(label, (hit or {}).get("raw"), want)

    # rate metrics: a "%" IS the value, so they opt in explicitly
    for label, want in (("Engagement rate", "3.55%"), ("Click through rate", "2.53%")):
        hit = dom.find_metric(page, [label], allow_percent=True)
        check(f"{label} (rate)", (hit or {}).get("raw"), want)
    # ...and a bare "%" next to a count must NOT be mistaken for the value
    hit = dom.find_metric(page, ["Impressions"])
    check("Impressions ignores the % delta", (hit or {}).get("raw"), "8,330")

    for label, want in (("Watch time", "1h 23m"), ("Average watch time", "0:21")):
        hit = dom.find_metric(page, [label], mode="text")
        check(f"{label} (text)", (hit or {}).get("raw"), want)


def main() -> int:
    test_parse_number()
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
        ctx.add_init_script(INSTALL_JS)
        page = ctx.new_page()
        page.goto((FIXTURES / "fixture_analytics.html").as_uri())
        test_overview(page)
        page.goto((FIXTURES / "fixture_post.html").as_uri())
        test_post(page)
        browser.close()
    print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
