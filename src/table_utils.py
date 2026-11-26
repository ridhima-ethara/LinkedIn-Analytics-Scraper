"""Helpers for turning the scraped table structures into row dictionaries."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

URN_RE = re.compile(r"urn:li:(?:activity|share|ugcPost):\d+")


def norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "")).strip().lower()


def find_table(tables: List[Dict[str, Any]], required: Sequence[str],
               any_of: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    """Best table whose headers contain all of `required` (and any of `any_of`)."""
    req = [norm_header(r) for r in required]
    anyo = [norm_header(a) for a in any_of]
    best = None
    for t in tables:
        headers = [norm_header(h) for h in t.get("headers", [])]
        if not headers:
            continue
        if not all(any(r in h for h in headers) for r in req):
            continue
        if anyo and not any(any(a in h for h in headers) for a in anyo):
            continue
        if best is None or len(t.get("rows", [])) > len(best.get("rows", [])):
            best = t
    return best


def row_dicts(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Zip header names onto each row, keeping the row's links."""
    headers = [norm_header(h) for h in table.get("headers", [])]
    out: List[Dict[str, Any]] = []
    for row in table.get("rows", []):
        cells = row.get("cells", [])
        rec: Dict[str, Any] = {"_cells": cells, "_links": row.get("links", [])}
        for i, cell in enumerate(cells):
            key = headers[i] if i < len(headers) else f"col{i}"
            # duplicate header names: keep the first, suffix the rest
            if key in rec:
                key = f"{key}_{i}"
            rec[key] = cell
        rec["_urn"] = urn_from(row)
        out.append(rec)
    return out


def urn_from(row: Dict[str, Any]) -> str:
    for link in row.get("links", []) or []:
        m = URN_RE.search(link or "")
        if m:
            return m.group(0)
    for cell in row.get("cells", []) or []:
        m = URN_RE.search(cell or "")
        if m:
            return m.group(0)
    return ""


def pick(rec: Dict[str, Any], *candidates: str) -> Optional[str]:
    """First cell whose header contains one of the candidate substrings."""
    for cand in candidates:
        c = norm_header(cand)
        for key, val in rec.items():
            if key.startswith("_"):
                continue
            if c in key:
                return val
    return None


def find_row(rows: List[Dict[str, Any]], pattern: str,
             column: Optional[str] = None) -> Optional[Dict[str, Any]]:
    rx = re.compile(pattern, re.I)
    for rec in rows:
        haystack = rec.get(norm_header(column), "") if column else " ".join(
            str(c) for c in rec.get("_cells", [])
        )
        if rx.search(haystack or ""):
            return rec
    return None
