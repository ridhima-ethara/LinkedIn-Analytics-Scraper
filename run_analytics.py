#!/usr/bin/env python3
"""LinkedIn Page Analytics extractor — Playwright + Firefox.

Usage
-----
  python run_analytics.py                                  # uses config.yaml
  python run_analytics.py --url https://www.linkedin.com/company/<id>/admin/analytics/updates/
  python run_analytics.py --headed --date-range past_90_days --max-posts 5
  python run_analytics.py --sections visitors,followers

Exit codes
----------
  0  run completed (reports written; individual metrics may still be unavailable)
  2  authenticated session missing/expired — run `python login.py` first
  3  fatal error before any section could run
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src import __version__
from src.browser import launch, save_session, session_store, verify_authenticated
from src.catalog import SECTION_CATEGORIES, build_metric_set
from src.config import ConfigError, load_config
from src import dates
from src.dom import SessionExpired
from src.logging_setup import get_logger, setup_logging
from src.models import Limitation
from src.reporting import print_console_summary, write_reports
from src.sections import ORDER, REGISTRY, RunContext

ROOT = Path(__file__).resolve().parent


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract LinkedIn Page analytics (Playwright/Firefox)")
    p.add_argument("--url", help="LinkedIn company page (admin analytics) URL")
    p.add_argument("--config", default=None, help="path to config.yaml")
    p.add_argument("--out", default=None, help="output directory (default: output/)")
    p.add_argument("--date-range", default=None,
                   help="past_7_days | past_28_days | past_30_days | past_90_days | "
                        "past_365_days | year_YYYY | custom | YYYY-MM-DD..YYYY-MM-DD | "
                        "keep_default")
    p.add_argument("--year", type=int, default=None,
                   help="calendar year window, e.g. --year 2026 (clamped to today)")
    p.add_argument("--start", default=None, help="window start, YYYY-MM-DD")
    p.add_argument("--end", default=None, help="window end, YYYY-MM-DD (default: today)")
    p.add_argument("--max-posts", type=int, default=None,
                   help="how many posts to open for individual post analytics")
    p.add_argument("--sections", default=None,
                   help="comma separated subset of: " + ",".join(REGISTRY))
    p.add_argument("--no-post-detail", action="store_true",
                   help="skip opening individual post analytics pages")
    p.add_argument("--headed", action="store_true", help="run Firefox with a visible window")
    p.add_argument("--headless", action="store_true", help="force headless (default)")
    p.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--run-id", default=None, help="override the run id / output folder name")
    return p.parse_args(argv)


def build_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    o: Dict[str, Any] = {}
    if args.url:
        o["company.url"] = args.url
    if args.date_range:
        o["extraction.date_range"] = args.date_range
    if args.year:
        o["extraction.date_range"] = f"year_{args.year}"
    if args.start or args.end:
        o["extraction.date_range"] = "custom"
        if args.start:
            o["extraction.custom_start"] = args.start
        if args.end:
            o["extraction.custom_end"] = args.end
    if args.max_posts is not None:
        o["extraction.max_posts"] = args.max_posts
    if args.no_post_detail:
        o["extraction.post_detail"] = False
    if args.sections:
        o["extraction.sections"] = [s.strip() for s in args.sections.split(",") if s.strip()]
    if args.headed:
        o["browser.headless"] = False
    if args.headless:
        o["browser.headless"] = True
    if args.log_level:
        o["logging.level"] = args.log_level
    if args.out:
        o["output.dir"] = args.out
    return o


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cfg = load_config(args.config, build_overrides(args))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 3

    started = datetime.now(timezone.utc)
    run_id = args.run_id or f"{started.strftime('%Y%m%dT%H%M%SZ')}_{cfg.company_slug}"
    log = setup_logging(cfg.logging_cfg.get("level", "INFO"),
                        cfg.abs_path(cfg.logging_cfg.get("dir", "logs")), run_id)
    log = get_logger("run")

    out_dir = cfg.abs_path(cfg.output.get("dir", "output")) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    requested = [s for s in (cfg.sections or list(REGISTRY))]
    unknown = [s for s in requested if s not in REGISTRY]
    if unknown:
        print(f"unknown section(s): {unknown}; valid: {list(REGISTRY)}", file=sys.stderr)
        return 3

    try:
        window = dates.resolve_window(cfg.extraction)
    except dates.DateWindowError as exc:
        print(f"invalid date range: {exc}", file=sys.stderr)
        return 3

    metrics = build_metric_set()
    bundle = None
    exit_code = 0
    store = session_store(cfg)

    run_meta: Dict[str, Any] = {
        "tool_version": __version__,
        "run_id": run_id,
        "company_url": cfg.company_url,
        "company_id": cfg.company_slug,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": None,
        "headless": bool(cfg.browser.get("headless", True)),
        "browser_engine": "firefox (playwright)",
        "date_range_requested": cfg.extraction.get("date_range"),
        "date_window_requested": dates.window_label(window) if window else None,
        "date_window_days": dates.window_days(window) if window else None,
        "date_range_applied": None,
        "date_range_verified": None,
        "date_range_verification": None,
        "sections_requested": requested,
        "session_file": str(store.location) if store.exists else None,
        "session_state": "unknown",
        "config_file": str(cfg.path),
    }

    ctx = RunContext(cfg=cfg, page=None, metrics=metrics, out_dir=out_dir,  # type: ignore[arg-type]
                     run_id=run_id, requested_range=str(cfg.extraction.get("date_range")),
                     date_window=window)
    if window:
        log.info("requested date window: %s (%d days)", dates.window_label(window),
                 dates.window_days(window))
        if dates.window_days(window) > dates.MAX_WINDOW_DAYS:
            log.warning("requested window exceeds LinkedIn's %d-day maximum",
                        dates.MAX_WINDOW_DAYS)

    try:
        bundle = launch(cfg)
        ctx.page = bundle.page
        run_meta["playwright_version"] = _pw_version()

        if not store.exists:
            raise SessionExpired(
                f"no persisted LinkedIn session at {store.plain_path} — run "
                f"`python login.py` (a human logs in once, including MFA)")

        info = verify_authenticated(bundle.page)
        run_meta["session_state"] = "valid"
        run_meta["account_hint"] = info.get("account_hint", "")

        for cls in ORDER:
            if cls.key not in requested:
                metrics.fail_section(SECTION_CATEGORIES.get(cls.key, []),
                                     f"section '{cls.key}' was not selected for this run "
                                     f"(--sections {','.join(requested)})",
                                     Limitation.NOT_ATTEMPTED)
                continue
            cls().run(ctx)

        save_session(bundle, cfg)

    except SessionExpired as exc:
        run_meta["session_state"] = f"expired/missing: {exc}"
        log.error("session problem: %s", exc)
        metrics.fail_section(
            [c for cats in SECTION_CATEGORIES.values() for c in cats],
            f"Authenticated LinkedIn session unavailable: {exc}",
            Limitation.SESSION_EXPIRED)
        if ctx.page:
            ctx.shot("session_failure")
        exit_code = 2
    except Exception as exc:  # noqa: BLE001
        log.error("fatal error: %s\n%s", exc, traceback.format_exc())
        run_meta["fatal_error"] = f"{type(exc).__name__}: {exc}"
        metrics.fail_section(
            [c for cats in SECTION_CATEGORIES.values() for c in cats],
            f"Run aborted by an unexpected error: {type(exc).__name__}: {exc}",
            Limitation.AUTOMATION_FAILURE)
        if ctx.page:
            ctx.shot("fatal_failure")
        exit_code = 3
    finally:
        if bundle:
            raw = bundle.recorder.dump(out_dir / "evidence" / "analytics_xhr.json")
            if raw:
                run_meta["raw_network_capture"] = raw
            bundle.close()

    run_meta["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_meta["date_range_applied"] = ctx.date_range
    run_meta["date_range_verified"] = ctx.date_range_verified
    run_meta["date_range_verification"] = ctx.date_range_explanation
    files = write_reports(ctx, run_meta)
    print_console_summary(ctx, files)
    (out_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2, default=str))
    return exit_code


def _pw_version() -> str:
    try:
        from importlib.metadata import version
        return version("playwright")
    except Exception:  # pragma: no cover
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
