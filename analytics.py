"""
analytics.py
============
Framework-free validation and metric logic for the API Feed Schema &
Integration-Health Monitor. No Streamlit, no pandas dependency required to run
these functions — they operate on plain Python lists/dicts so they can be
unit-tested in isolation (see test_analytics.py).

Responsibilities:
  * validate a single record against an expected schema
  * validate a whole feed and return a flat list of violations
  * roll violations up into KPIs, per-source health, and freshness/sync-lag
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Violation categories (stable strings used by the UI and the tests).
MISSING_FIELD = "missing_field"
NULL_VIOLATION = "null_violation"
TYPE_MISMATCH = "type_mismatch"
ENUM_VIOLATION = "enum_violation"
RANGE_VIOLATION = "range_violation"
FORMAT_ERROR = "format_error"


# ---------------------------------------------------------------------------
# Low-level type / datetime helpers
# ---------------------------------------------------------------------------
def parse_datetime(value: Any) -> datetime | None:
    """
    Parse an ISO-8601 string into a timezone-aware datetime, or return None if
    it cannot be parsed. Naive datetimes are assumed UTC.
    """
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "str":
        return isinstance(value, str)
    if expected == "number":
        # bool is a subclass of int in Python; exclude it explicitly.
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "datetime":
        return parse_datetime(value) is not None
    raise ValueError(f"Unknown expected type: {expected!r}")


def _violation(record_id: Any, field: str, category: str, detail: str) -> dict[str, Any]:
    return {
        "record_id": record_id if record_id is not None else "<missing id>",
        "field": field,
        "category": category,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Record- and feed-level validation
# ---------------------------------------------------------------------------
def validate_record(
    record: dict[str, Any], schema: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Validate one record against `schema`. Returns a list of violation dicts
    (empty list == fully valid). Each field is checked in a fixed order so
    output is deterministic.
    """
    violations: list[dict[str, Any]] = []
    rid = record.get("record_id")

    for field, rule in schema.items():
        present = field in record
        value = record.get(field)

        # 1. Presence
        if not present:
            if rule.get("required", False):
                violations.append(
                    _violation(rid, field, MISSING_FIELD,
                               "required field is absent")
                )
            continue

        # 2. Null handling
        if value is None:
            if not rule.get("nullable", False):
                violations.append(
                    _violation(rid, field, NULL_VIOLATION,
                               "null in a non-nullable field")
                )
            continue  # no further checks on a null

        # 3. Type
        expected_type = rule["type"]
        if not _type_ok(value, expected_type):
            # A bad datetime string is reported as a format error, not a plain
            # type mismatch, because the field IS a string — it just won't parse.
            if expected_type == "datetime" and isinstance(value, str):
                violations.append(
                    _violation(rid, field, FORMAT_ERROR,
                               f"unparseable datetime: {value!r}")
                )
            else:
                violations.append(
                    _violation(rid, field, TYPE_MISMATCH,
                               f"expected {expected_type}, got "
                               f"{type(value).__name__} ({value!r})")
                )
            continue  # type is wrong, skip enum/range

        # 4. Enum
        if "enum" in rule and value not in rule["enum"]:
            violations.append(
                _violation(rid, field, ENUM_VIOLATION,
                           f"{value!r} not in allowed values")
            )

        # 5. Numeric range
        if expected_type == "number":
            if "min" in rule and value < rule["min"]:
                violations.append(
                    _violation(rid, field, RANGE_VIOLATION,
                               f"{value} below minimum {rule['min']}")
                )
            if "max" in rule and value > rule["max"]:
                violations.append(
                    _violation(rid, field, RANGE_VIOLATION,
                               f"{value} above maximum {rule['max']}")
                )

    return violations


def validate_feed(
    feed: list[dict[str, Any]], schema: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Validate every record in `feed`. Returns a flat list of violations, each
    augmented with the record's row index and source system for later grouping.
    """
    all_violations: list[dict[str, Any]] = []
    for idx, record in enumerate(feed):
        for v in validate_record(record, schema):
            v = dict(v)
            v["row_index"] = idx
            v["source_system"] = record.get("source_system", "<unknown>")
            all_violations.append(v)
    return all_violations


def invalid_row_indices(
    feed: list[dict[str, Any]], schema: dict[str, dict[str, Any]]
) -> set[int]:
    """Row indices of records with at least one violation."""
    return {v["row_index"] for v in validate_feed(feed, schema)}


# ---------------------------------------------------------------------------
# Roll-ups: KPIs, per-source health, freshness
# ---------------------------------------------------------------------------
def compute_kpis(
    feed: list[dict[str, Any]],
    schema: dict[str, dict[str, Any]],
    now: datetime | None = None,
    stale_threshold_hours: float = 24.0,
) -> dict[str, Any]:
    """
    Headline KPIs for the tiles:
      connected_sources, records_ingested, schema_valid_pct,
      integration_uptime_pct, open_issues.

    integration_uptime_pct is defined as the share of source systems whose most
    recent successful sync is within `stale_threshold_hours` of `now`.
    """
    total = len(feed)
    bad_rows = invalid_row_indices(feed, schema)
    valid_rows = total - len(bad_rows)
    violations = validate_feed(feed, schema)

    # Connected sources = distinct, recognized source systems seen in the feed.
    known_sources = set(schema.get("source_system", {}).get("enum", []))
    seen_sources = {r.get("source_system") for r in feed}
    connected = len(seen_sources & known_sources) if known_sources else len(seen_sources)

    fresh = freshness_by_source(feed, now=now, stale_threshold_hours=stale_threshold_hours)
    if fresh:
        up = sum(1 for s in fresh if not s["is_stale"])
        uptime_pct = round(100.0 * up / len(fresh), 1)
    else:
        uptime_pct = 0.0

    return {
        "connected_sources": connected,
        "records_ingested": total,
        "schema_valid_pct": round(100.0 * valid_rows / total, 1) if total else 0.0,
        "valid_records": valid_rows,
        "invalid_records": len(bad_rows),
        "integration_uptime_pct": uptime_pct,
        "open_issues": len(violations),
    }


def source_health(
    feed: list[dict[str, Any]], schema: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Per-source integration health: record count, count of records with >=1
    violation, and the resulting error rate (%). Sorted by error rate desc.
    """
    bad_rows = invalid_row_indices(feed, schema)
    buckets: dict[str, dict[str, int]] = {}
    for idx, record in enumerate(feed):
        src = record.get("source_system", "<unknown>")
        b = buckets.setdefault(src, {"records": 0, "error_records": 0})
        b["records"] += 1
        if idx in bad_rows:
            b["error_records"] += 1

    rows: list[dict[str, Any]] = []
    for src, b in buckets.items():
        recs = b["records"]
        errs = b["error_records"]
        rows.append(
            {
                "source_system": src,
                "records": recs,
                "error_records": errs,
                "error_rate_pct": round(100.0 * errs / recs, 1) if recs else 0.0,
            }
        )
    rows.sort(key=lambda r: (-r["error_rate_pct"], -r["records"]))
    return rows


def sync_lag_minutes(record: dict[str, Any]) -> float | None:
    """synced_at - created_at in minutes, or None if either is unparseable."""
    created = parse_datetime(record.get("created_at"))
    synced = parse_datetime(record.get("synced_at"))
    if created is None or synced is None:
        return None
    return (synced - created).total_seconds() / 60.0


def freshness_by_source(
    feed: list[dict[str, Any]],
    now: datetime | None = None,
    stale_threshold_hours: float = 24.0,
) -> list[dict[str, Any]]:
    """
    Per-source freshness / sync-lag:
      median_lag_min  : typical created->synced lag
      last_sync        : most recent synced_at
      hours_since_sync : how long ago the last sync landed (vs `now`)
      is_stale         : hours_since_sync > stale_threshold_hours
    Sorted by hours_since_sync desc (stalest first).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    buckets: dict[str, dict[str, Any]] = {}
    for record in feed:
        src = record.get("source_system", "<unknown>")
        b = buckets.setdefault(src, {"lags": [], "last_sync": None})
        lag = sync_lag_minutes(record)
        if lag is not None:
            b["lags"].append(lag)
        synced = parse_datetime(record.get("synced_at"))
        if synced is not None:
            if b["last_sync"] is None or synced > b["last_sync"]:
                b["last_sync"] = synced

    rows: list[dict[str, Any]] = []
    for src, b in buckets.items():
        lags = sorted(b["lags"])
        median = _median(lags)
        last_sync = b["last_sync"]
        if last_sync is not None:
            hours_since = (now - last_sync).total_seconds() / 3600.0
        else:
            hours_since = None
        rows.append(
            {
                "source_system": src,
                "median_lag_min": round(median, 1) if median is not None else None,
                "last_sync": last_sync.isoformat() if last_sync else None,
                "hours_since_sync": round(hours_since, 1) if hours_since is not None else None,
                "is_stale": (hours_since is not None and hours_since > stale_threshold_hours),
            }
        )
    rows.sort(key=lambda r: (r["hours_since_sync"] is not None, r["hours_since_sync"] or 0.0),
              reverse=True)
    return rows


def violations_by_category(violations: list[dict[str, Any]]) -> dict[str, int]:
    """Count violations grouped by category."""
    counts: dict[str, int] = {}
    for v in violations:
        counts[v["category"]] = counts.get(v["category"], 0) + 1
    return counts


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0
