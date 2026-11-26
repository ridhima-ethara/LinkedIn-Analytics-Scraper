"""Playwright **Firefox** browser lifecycle (no Selenium, no Chromium).

Also provides passive capture of the analytics XHR payloads the page itself
fetches while authenticated — recorded for evidence/debugging only. The tool
never issues its own API calls and never attempts to bypass authentication.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import (Browser, BrowserContext, Error as PwError, Page,
                                 Playwright, Response, sync_playwright)

from .config import Config
from .dom import SessionExpired, guard_session
from .jsfuncs import INSTALL_JS
from .logging_setup import get_logger
from .session_store import SessionStore

log = get_logger("browser")

ANALYTICS_XHR_HINTS = (
    "/voyager/api/organization",
    "/voyager/api/organizationDashboard",
    "analytics",
    "organizationalPage",
)


@dataclass
class NetworkRecorder:
    """Passively records the page's own analytics responses."""

    enabled: bool = False
    max_records: int = 400
    records: List[Dict[str, Any]] = field(default_factory=list)

    def attach(self, context: BrowserContext) -> None:
        if not self.enabled:
            return
        context.on("response", self._on_response)

    def _on_response(self, response: Response) -> None:
        try:
            url = response.url
            if not any(h in url for h in ANALYTICS_XHR_HINTS):
                return
            if len(self.records) >= self.max_records:
                return
            rec: Dict[str, Any] = {"url": url, "status": response.status,
                                   "method": response.request.method}
            ctype = (response.headers or {}).get("content-type", "")
            if "json" in ctype:
                try:
                    body = response.json()
                    rec["body"] = body
                except Exception:  # body may be gone / not json
                    rec["body"] = None
            self.records.append(rec)
        except Exception as exc:  # never let instrumentation break a run
            log.debug("network record skipped: %s", exc)

    def dump(self, path: Path) -> Optional[str]:
        if not self.enabled or not self.records:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.records, indent=2, default=str))
        log.info("captured %d analytics XHR payload(s) -> %s", len(self.records), path)
        return str(path)


@dataclass
class BrowserBundle:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    recorder: NetworkRecorder

    def close(self) -> None:
        for closer in (self.context.close, self.browser.close, self.playwright.stop):
            try:
                closer()
            except Exception as exc:  # pragma: no cover
                log.debug("close step failed: %s", exc)


def session_store(cfg: Config) -> SessionStore:
    s = cfg.session
    return SessionStore(
        path=cfg.abs_path(s.get("storage_state_path", "secrets/linkedin_state.json")),
        encrypt=bool(s.get("encrypt", True)),
        key_env=s.get("key_env", "LI_SESSION_KEY"),
        key_file=cfg.abs_path(s.get("key_file", "secrets/session.key")),
    )


def launch(cfg: Config, *, headless: Optional[bool] = None,
           use_session: bool = True, record_network: Optional[bool] = None) -> BrowserBundle:
    b = cfg.browser
    engine = str(b.get("engine", "firefox")).lower()
    if engine != "firefox":
        raise ValueError(f"only Playwright Firefox is supported, got engine={engine!r}")

    headless = b.get("headless", True) if headless is None else headless
    pw = sync_playwright().start()
    accept_lang = b.get("accept_language", "en-US,en;q=0.9")
    browser = pw.firefox.launch(
        headless=bool(headless),
        slow_mo=int(b.get("slow_mo_ms", 0) or 0),
        firefox_user_prefs={
            "intl.accept_languages": accept_lang,
            # keep automation stable on small EC2 instances
            "media.autoplay.default": 5,
            "media.volume_scale": "0.0",
            "dom.webnotifications.enabled": False,
            "browser.cache.disk.enable": False,
        },
    )

    storage_state = None
    if use_session:
        store = session_store(cfg)
        storage_state = store.load()
        if storage_state:
            log.info("loaded persisted session from %s (%d cookies)",
                     store.location, len(storage_state.get("cookies", [])))
        else:
            log.warning("no persisted session found at %s — run `python login.py` first",
                        store.plain_path)

    vp = b.get("viewport", {}) or {}
    context = browser.new_context(
        viewport={"width": int(vp.get("width", 1600)), "height": int(vp.get("height", 1200))},
        locale=b.get("locale", "en-US"),
        timezone_id=b.get("timezone", "UTC"),
        storage_state=storage_state,
        extra_http_headers={"Accept-Language": accept_lang},
    )
    context.set_default_timeout(int(b.get("action_timeout_ms", 20000)))
    context.set_default_navigation_timeout(int(b.get("nav_timeout_ms", 60000)))
    context.add_init_script(INSTALL_JS)

    recorder = NetworkRecorder(
        enabled=bool(cfg.output.get("save_raw_network", True)
                     if record_network is None else record_network)
    )
    recorder.attach(context)

    page = context.new_page()
    log.info("launched Playwright Firefox (headless=%s)", bool(headless))
    return BrowserBundle(pw, browser, context, page, recorder)


def verify_authenticated(page: Page, timeout_ms: int = 45000) -> Dict[str, Any]:
    """Confirm the persisted session is still valid.

    Raises SessionExpired with an actionable message when it is not.
    """
    url = "https://www.linkedin.com/feed/"
    log.info("verifying session via %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(2500)
    guard_session(page)
    cookies = {c["name"] for c in page.context.cookies("https://www.linkedin.com")}
    if "li_at" not in cookies:
        raise SessionExpired(
            "no li_at cookie in the context — the stored session is empty or expired; "
            "re-run `python login.py`"
        )
    me = ""
    try:
        me = page.evaluate(
            "() => { const a = document.querySelector("
            "'.global-nav__me-photo, img.global-nav__me-photo, "
            "[data-test-global-nav-me] img'); return a ? (a.alt || '') : ''; }"
        ) or ""
    except PwError:
        pass
    log.info("session OK%s", f" (signed in as {me})" if me else "")
    return {"authenticated": True, "account_hint": me, "verified_url": page.url}


def save_session(bundle: BrowserBundle, cfg: Config) -> Optional[str]:
    """Refresh the persisted session (LinkedIn rotates cookies)."""
    try:
        state = bundle.context.storage_state()
        return str(session_store(cfg).save(state))
    except Exception as exc:
        log.warning("could not refresh persisted session: %s", exc)
        return None
