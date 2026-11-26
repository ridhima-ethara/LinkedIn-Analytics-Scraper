"""Configuration loading: config.yaml + .env + CLI overrides."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml

try:  # optional, only to populate os.environ from .env
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent

_COMPANY_RE = re.compile(r"/company/([^/?#]+)", re.I)


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    raw: Dict[str, Any]
    path: Path

    # resolved values
    company_url: str = ""
    company_slug: str = ""
    company_base: str = ""      # https://www.linkedin.com/company/<slug>

    def __post_init__(self) -> None:
        self._resolve_company()

    # -- sections ---------------------------------------------------------
    @property
    def browser(self) -> Dict[str, Any]:
        return self.raw.get("browser", {}) or {}

    @property
    def session(self) -> Dict[str, Any]:
        return self.raw.get("session", {}) or {}

    @property
    def extraction(self) -> Dict[str, Any]:
        return self.raw.get("extraction", {}) or {}

    @property
    def output(self) -> Dict[str, Any]:
        return self.raw.get("output", {}) or {}

    @property
    def logging_cfg(self) -> Dict[str, Any]:
        return self.raw.get("logging", {}) or {}

    @property
    def urls(self) -> Dict[str, Any]:
        return self.raw.get("urls", {}) or {}

    @property
    def sections(self) -> List[str]:
        return list(self.extraction.get("sections") or [])

    def abs_path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else ROOT / p

    # -- helpers ----------------------------------------------------------
    def _resolve_company(self) -> None:
        url = (self.raw.get("company", {}) or {}).get("url", "")
        url = (url or "").strip()
        if not url:
            raise ConfigError("company.url is required (or pass --url)")
        parsed = urlparse(url)
        if parsed.netloc and "linkedin.com" not in parsed.netloc.lower():
            raise ConfigError(f"company.url must be a linkedin.com URL, got {url!r}")
        m = _COMPANY_RE.search(url)
        if not m:
            raise ConfigError(
                f"Could not find /company/<id> in {url!r}. "
                "Pass the company admin URL, e.g. "
                "https://www.linkedin.com/company/12345678/admin/analytics/updates/"
            )
        self.company_url = url
        self.company_slug = m.group(1)
        self.company_base = f"https://www.linkedin.com/company/{self.company_slug}"

    def section_url(self, name: str, default_path: str) -> str:
        """Config override wins; otherwise build from the company base URL."""
        override = self.urls.get(name)
        if override:
            return str(override).replace("{base}", self.company_base)
        return f"{self.company_base}{default_path}"

    def post_summary_templates(self) -> List[str]:
        tpls = self.urls.get("post_summary_templates") or [
            "https://www.linkedin.com/analytics/post-summary/{urn}/",
            "{base}/admin/analytics/post-summary/{urn}/",
        ]
        return [str(t).replace("{base}", self.company_base) for t in tpls]


def _env_overrides(raw: Dict[str, Any]) -> None:
    mapping = {
        "LIA_COMPANY_URL": ("company", "url", str),
        "LIA_HEADLESS": ("browser", "headless", lambda v: str(v).lower() in ("1", "true", "yes")),
        "LIA_DATE_RANGE": ("extraction", "date_range", str),
        "LIA_MAX_POSTS": ("extraction", "max_posts", int),
    }
    for env, (section, key, cast) in mapping.items():
        val = os.environ.get(env)
        if val not in (None, ""):
            raw.setdefault(section, {})[key] = cast(val)


def load_config(config_path: Optional[str] = None,
                overrides: Optional[Dict[str, Any]] = None) -> Config:
    """Load config.yaml, apply .env then env-var then CLI overrides."""
    if load_dotenv:
        load_dotenv(ROOT / ".env", override=False)

    path = Path(config_path) if config_path else ROOT / "config.yaml"
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}

    _env_overrides(raw)

    for dotted, value in (overrides or {}).items():
        if value is None:
            continue
        section, _, key = dotted.partition(".")
        if not key:
            raw[section] = value
        else:
            raw.setdefault(section, {})[key] = value

    return Config(raw=raw, path=path)
