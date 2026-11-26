"""Metric record model and the status / limitation vocabulary used in reports."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Status:
    """Extraction outcome for a single metric."""

    EXTRACTED = "extracted"        # value captured from the live page
    PARTIAL = "partial"            # some of the metric captured (e.g. 3 of 5 demographic buckets)
    NOT_ACCESSIBLE = "not_accessible"


class Limitation:
    """Why a metric is not fully extracted. Mutually exclusive, most specific wins."""

    NONE = "none"
    LINKEDIN_UI = "linkedin_ui"                # metric is not surfaced by the admin UI (or UI changed)
    PERMISSIONS = "permissions"                # page/role does not grant access to this section
    DATA_UNAVAILABLE = "data_unavailable"      # UI present but LinkedIn reports no data for the range
    AUTOMATION_FAILURE = "automation_failure"  # our navigation/parse failed
    SESSION_EXPIRED = "session_expired"        # authentication wall hit mid-run
    NOT_ATTEMPTED = "not_attempted"            # section disabled/skipped


@dataclass
class Metric:
    """One row of the output report."""

    metric_name: str
    category: str
    source_section: str
    value: Optional[Any] = None
    raw_value: Optional[str] = None
    unit: str = ""
    date_range: str = ""
    status: str = Status.NOT_ACCESSIBLE
    limitation: str = Limitation.NOT_ATTEMPTED
    reason: str = "Not attempted yet."
    source_url: str = ""
    evidence: str = ""        # the exact on-page text the value was read from
    strategy: str = ""        # which extraction strategy produced it
    entity: str = ""          # post URN / demographic bucket, when the metric is scoped
    requested: bool = False   # True = part of the requested metric catalog
    panel: str = ""           # LinkedIn panel the metric is shown in
    breakdown: str = ""       # breakdown label as named in the LinkedIn UI
    detail: Dict[str, Any] = field(default_factory=dict)
    extracted_at: str = field(default_factory=_now)

    # -- outcome setters ---------------------------------------------------
    def ok(self, value: Any, raw: str = "", *, date_range: str = "", url: str = "",
           evidence: str = "", strategy: str = "", unit: str = "",
           detail: Optional[Dict[str, Any]] = None) -> "Metric":
        self.value = value
        self.raw_value = raw or (str(value) if value is not None else None)
        self.status = Status.EXTRACTED
        self.limitation = Limitation.NONE
        self.reason = ""
        self.unit = unit or self.unit
        if date_range:
            self.date_range = date_range
        if url:
            self.source_url = url
        self.evidence = (evidence or "")[:400]
        self.strategy = strategy or self.strategy
        if detail:
            self.detail.update(detail)
        self.extracted_at = _now()
        return self

    def partial(self, value: Any, reason: str, limitation: str = Limitation.LINKEDIN_UI,
                **kw) -> "Metric":
        self.ok(value, **kw)
        self.status = Status.PARTIAL
        self.limitation = limitation
        self.reason = reason
        return self

    def fail(self, reason: str, limitation: str = Limitation.AUTOMATION_FAILURE, *,
             url: str = "", evidence: str = "", date_range: str = "") -> "Metric":
        self.value = None
        self.raw_value = None
        self.status = Status.NOT_ACCESSIBLE
        self.limitation = limitation
        self.reason = reason
        if url:
            self.source_url = url
        if date_range:
            self.date_range = date_range
        if evidence:
            self.evidence = evidence[:400]
        self.extracted_at = _now()
        return self

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def key(self) -> str:
        return f"{self.category}|{self.metric_name}|{self.entity}"


class MetricSet:
    """Holds the full expected-metric catalog so nothing silently disappears.

    Every metric the task asks for is pre-registered as `not_accessible /
    not_attempted`. Sections then promote entries to extracted/partial. Anything
    still untouched at the end is reported with the reason it was never reached,
    which is what makes the Unavailable Metrics Report trustworthy.
    """

    def __init__(self) -> None:
        self._metrics: Dict[str, Metric] = {}
        self._order: List[str] = []

    def register(self, metric: Metric) -> Metric:
        if metric.key not in self._metrics:
            self._metrics[metric.key] = metric
            self._order.append(metric.key)
        return self._metrics[metric.key]

    def get(self, category: str, metric_name: str, entity: str = "") -> Optional[Metric]:
        return self._metrics.get(f"{category}|{metric_name}|{entity}")

    def require(self, category: str, metric_name: str, source_section: str = "",
                entity: str = "") -> Metric:
        """Fetch a catalog metric, creating it if a section discovers an extra one."""
        existing = self.get(category, metric_name, entity)
        if existing:
            if source_section and not existing.source_section:
                existing.source_section = source_section
            return existing
        from .catalog import panel_for  # local import avoids a cycle
        panel, breakdown = panel_for(category, metric_name)
        return self.register(
            Metric(metric_name=metric_name, category=category,
                   source_section=source_section, entity=entity,
                   panel=panel, breakdown=breakdown)
        )

    def all(self) -> List[Metric]:
        return [self._metrics[k] for k in self._order]

    def by_status(self, status: str) -> List[Metric]:
        return [m for m in self.all() if m.status == status]

    def fail_section(self, category_prefixes: List[str], reason: str, limitation: str,
                     url: str = "") -> None:
        """Mark every still-unattempted metric of a section with a concrete reason."""
        for m in self.all():
            if m.status == Status.NOT_ACCESSIBLE and m.limitation == Limitation.NOT_ATTEMPTED:
                if any(m.category.startswith(p) for p in category_prefixes):
                    m.fail(reason, limitation, url=url)
