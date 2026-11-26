#!/usr/bin/env python3
"""One-time authenticated-session bootstrap.

The script never types credentials and never automates a login form: a human
signs in (including MFA / 2FA) in a visible Firefox window, and only the
resulting session state is persisted — encrypted at rest.

Modes
-----
  python login.py                 # visible Firefox, log in by hand, session saved
  python login.py --check         # validate the stored session headlessly
  python login.py --from-cookie-env
                                  # headless server: import the li_at cookie you
                                  # exported from your own browser (see EC2_SETUP.md)
  python login.py --clear         # delete the stored session
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import List

from src.browser import launch, session_store, verify_authenticated
from src.config import ConfigError, load_config
from src.dom import SessionExpired
from src.logging_setup import get_logger, setup_logging

LOGIN_URL = "https://www.linkedin.com/login"


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create/validate a LinkedIn session for the extractor")
    p.add_argument("--config", default=None)
    p.add_argument("--check", action="store_true", help="only validate the stored session")
    p.add_argument("--clear", action="store_true", help="delete the stored session")
    p.add_argument("--from-cookie-env", action="store_true",
                   help="import LI_AT (+ optional LI_JSESSIONID) from the environment/.env")
    p.add_argument("--timeout", type=int, default=None,
                   help="seconds to wait for the manual login (default: config)")
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 3
    setup_logging(cfg.logging_cfg.get("level", "INFO"),
                  cfg.abs_path(cfg.logging_cfg.get("dir", "logs")),
                  f"login_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    log = get_logger("login")
    store = session_store(cfg)

    if args.clear:
        removed = []
        for path in (store.enc_path, store.plain_path):
            if path.exists():
                path.unlink()
                removed.append(str(path))
        print("removed:", removed or "nothing to remove")
        return 0

    if args.check:
        if not store.exists:
            print(f"no session stored at {store.plain_path} (.enc)")
            return 2
        bundle = launch(cfg, headless=True)
        try:
            info = verify_authenticated(bundle.page)
            print(f"session OK ({store.location}); cookies: {store.cookie_names()}")
            print(f"verified at {info['verified_url']}")
            return 0
        except SessionExpired as exc:
            print(f"session INVALID: {exc}", file=sys.stderr)
            return 2
        finally:
            bundle.close()

    if args.from_cookie_env:
        li_at = os.environ.get("LI_AT", "").strip()
        if not li_at:
            print("LI_AT is not set. Export the li_at cookie value from a browser where "
                  "you are already signed in to your own LinkedIn account, e.g.\n"
                  "  export LI_AT='...'\n"
                  "then re-run:  python login.py --from-cookie-env", file=sys.stderr)
            return 3
        state = store.state_from_cookies(li_at, os.environ.get("LI_JSESSIONID", "").strip())
        store.save(state)
        print(f"session stored -> {store.location}")
        bundle = launch(cfg, headless=True)
        try:
            verify_authenticated(bundle.page)
            print("imported session verified against linkedin.com/feed")
            return 0
        except SessionExpired as exc:
            print(f"imported cookie did not authenticate: {exc}", file=sys.stderr)
            return 2
        finally:
            bundle.close()

    # ---- interactive manual login (default) -----------------------------
    timeout_s = int(args.timeout or cfg.session.get("manual_login_timeout_s", 420))
    bundle = launch(cfg, headless=False, use_session=False, record_network=False)
    page = bundle.page
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("\n" + "=" * 72)
        print("A Firefox window is open. Sign in to LinkedIn yourself, including any")
        print("MFA / 2FA step. Nothing is typed for you and no credentials are stored.")
        print(f"Waiting up to {timeout_s}s for the session to become valid...")
        print("=" * 72 + "\n")

        deadline = timeout_s
        while deadline > 0:
            page.wait_for_timeout(3000)
            deadline -= 3
            cookies = {c["name"] for c in bundle.context.cookies("https://www.linkedin.com")}
            url = page.url or ""
            if "li_at" in cookies and "/login" not in url and "checkpoint" not in url:
                log.info("li_at cookie present at %s", url)
                break
        else:
            print("timed out waiting for login; nothing was saved", file=sys.stderr)
            return 2

        # settle on an authenticated page before snapshotting the state
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        admin_url = cfg.company_url
        print(f"checking admin access to {admin_url}")
        page.goto(admin_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        final_url = page.url

        path = store.save(bundle.context.storage_state())
        print(f"\nsession saved -> {path}")
        print(f"landed on: {final_url}")
        if "/admin/" not in final_url:
            print("WARNING: LinkedIn did not keep you on the admin analytics URL. If this "
                  "account is not an admin of that Page, analytics sections will be "
                  "reported as permission-limited.", file=sys.stderr)
        print("\nnext:  python run_analytics.py")
        return 0
    finally:
        bundle.close()


if __name__ == "__main__":
    raise SystemExit(main())
