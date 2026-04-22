"""Feature pre-processing for the summary pipeline.

Converts the flat ``category_spending_profile`` dict (from Finbox) into the
``monthly_spend_breakdown`` list structure consumed by the LLM pipeline and
savings-dip attribution logic.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

_TOTAL_SPEND_RE = re.compile(r"^(?P<category>.+)_total_spend_m(?P<month>\d{1,2})$")
_FINBOX_SPEND_RE = re.compile(
    r"^total_(?:essential|discretionary)_spends_(?P<category>[a-z_]+)_m(?P<month>\d{1,2})$"
)


def _parse_json_if_needed(value: Any) -> Any:
    """Decode JSON-encoded strings (mirrors insight features helper)."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def convert_category_spending_to_breakdown(
    profile: Dict[str, Any],
    reference_dates: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Convert a flat ``category_spending_profile`` dict into ``monthly_spend_breakdown``.

    Input keys follow either ``{category}_total_spend_m{N}`` or
    ``total_{essential|discretionary}_spends_{category}_m{N}`` where *N* is a
    relative month index (0 = most recent, 12 = oldest).

    *reference_dates* is an optional list of ISO date strings sorted newest-first
    (e.g. ``["2026-04-30", "2026-03-31", ...]``).  When provided, month index *N*
    is mapped to ``reference_dates[N]`` so the output uses real dates instead of
    ``"m0"``, ``"m1"`` placeholders.

    Returns a list of ``{"month": "<date_or_mN>", "categories": {...}}`` dicts
    sorted chronologically (oldest first).
    """
    profile = _parse_json_if_needed(profile)
    if not isinstance(profile, dict):
        return []

    months: Dict[int, Dict[str, float]] = {}

    for key, value in profile.items():
        if not isinstance(key, str):
            continue
        m = _TOTAL_SPEND_RE.match(key) or _FINBOX_SPEND_RE.match(key)
        if not m:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        fval = float(value)
        if fval == 0.0:
            continue

        category = m.group("category")
        month_idx = int(m.group("month"))

        if month_idx not in months:
            months[month_idx] = {}
        months[month_idx][category] = fval

    ref = reference_dates or []

    def _month_key(idx: int) -> str | None:
        if ref:
            return ref[idx] if idx < len(ref) else None
        return f"m{idx}"

    return [
        {"month": mk, "categories": cats}
        for idx, cats in sorted(months.items(), reverse=True)
        if cats and (mk := _month_key(idx)) is not None
    ]
