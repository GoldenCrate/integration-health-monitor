"""
data_gen.py
===========
Generates a SYNTHETIC multi-source API/JSON feed that imitates what a unified
construction-data API would receive from several upstream source systems
(e.g. Procore, Autodesk Build, Sage 300, QuickBooks Online, Bluebeam).

Everything here is FAKE. No real company, project, vendor, or financial data is
used. The generator runs off a fixed random seed so the feed, and therefore the
schema-validation results, are fully reproducible.

The module also publishes EXPECTED_SCHEMA: the data-model contract the unified
API expects every incoming record to satisfy. data_gen deliberately injects a
known set of schema violations (missing fields, type mismatches, null
violations, out-of-range values, bad enums, unparseable timestamps) so that the
validator in analytics.py has real defects to catch.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Fixed reference "now" so sync-lag / freshness numbers are reproducible.
# ---------------------------------------------------------------------------
REFERENCE_NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)

SOURCE_SYSTEMS = [
    "Procore",
    "Autodesk Build",
    "Sage 300 CRE",
    "QuickBooks Online",
    "Bluebeam",
]

# ---------------------------------------------------------------------------
# EXPECTED SCHEMA — the data-model contract for one "cost record" in the feed.
#
# Each field declares:
#   type      : "str" | "number" | "datetime"
#   required  : must the key be present?
#   nullable  : is an explicit null allowed?
#   enum      : (optional) allowed values
#   min / max : (optional) inclusive numeric range
# ---------------------------------------------------------------------------
EXPECTED_SCHEMA: dict[str, dict[str, Any]] = {
    "record_id": {"type": "str", "required": True, "nullable": False},
    "source_system": {
        "type": "str",
        "required": True,
        "nullable": False,
        "enum": SOURCE_SYSTEMS,
    },
    "project_id": {"type": "str", "required": True, "nullable": False},
    "amount": {
        "type": "number",
        "required": True,
        "nullable": False,
        "min": 0,
        "max": 10_000_000,
    },
    "currency": {
        "type": "str",
        "required": True,
        "nullable": False,
        "enum": ["USD", "CAD", "EUR"],
    },
    "status": {
        "type": "str",
        "required": True,
        "nullable": False,
        "enum": ["draft", "pending", "approved", "paid", "void"],
    },
    "cost_code": {"type": "str", "required": True, "nullable": False},
    "vendor_name": {"type": "str", "required": False, "nullable": True},
    "created_at": {"type": "datetime", "required": True, "nullable": False},
    "synced_at": {"type": "datetime", "required": True, "nullable": False},
}

# Typical sync lag (in minutes) per source — some integrations are near
# real-time, others batch overnight. Used to make the freshness view realistic.
_TYPICAL_LAG_MIN = {
    "Procore": 8,
    "Autodesk Build": 15,
    "Sage 300 CRE": 720,       # nightly batch
    "QuickBooks Online": 45,
    "Bluebeam": 120,
}


def _iso(dt: datetime) -> str:
    """Serialize a datetime to an ISO-8601 string (what an API would return)."""
    return dt.isoformat()


def _clean_record(rng: random.Random, idx: int, source: str) -> dict[str, Any]:
    """Build one fully schema-valid record."""
    created = REFERENCE_NOW - timedelta(
        days=rng.randint(0, 30),
        hours=rng.randint(0, 23),
        minutes=rng.randint(0, 59),
    )
    lag = _TYPICAL_LAG_MIN[source] + rng.randint(-5, 20)
    synced = created + timedelta(minutes=max(1, lag))
    return {
        "record_id": f"REC-{idx:05d}",
        "source_system": source,
        "project_id": f"PRJ-{rng.randint(1000, 1012)}",
        "amount": round(rng.uniform(500, 250_000), 2),
        "currency": rng.choice(["USD", "USD", "USD", "CAD", "EUR"]),
        "status": rng.choice(["draft", "pending", "approved", "paid", "void"]),
        "cost_code": f"{rng.randint(1, 16):02d}-{rng.randint(1000, 9999)}",
        "vendor_name": rng.choice(
            [
                "Ironwood Concrete",
                "Summit Electrical",
                "BayState Plumbing",
                "Granite Steel Co",
                None,  # legitimately-null vendor is allowed by schema
            ]
        ),
        "created_at": _iso(created),
        "synced_at": _iso(synced),
    }


# Deterministic defect injectors. Each takes a clean record and corrupts it in
# one specific, catalogued way so the validator has something concrete to find.
def _inj_missing_required(rec: dict[str, Any]) -> dict[str, Any]:
    rec.pop("cost_code", None)              # missing required field
    return rec


def _inj_null_violation(rec: dict[str, Any]) -> dict[str, Any]:
    rec["project_id"] = None                # null in a non-nullable field
    return rec


def _inj_type_mismatch(rec: dict[str, Any]) -> dict[str, Any]:
    rec["amount"] = "1,250.00"              # number delivered as string
    return rec


def _inj_range_low(rec: dict[str, Any]) -> dict[str, Any]:
    rec["amount"] = -480.25                 # below min (negative cost)
    return rec


def _inj_range_high(rec: dict[str, Any]) -> dict[str, Any]:
    rec["amount"] = 48_500_000.0            # above max (likely unit error)
    return rec


def _inj_bad_enum(rec: dict[str, Any]) -> dict[str, Any]:
    rec["status"] = "APPROVED!"             # not in allowed status enum
    return rec


def _inj_bad_source(rec: dict[str, Any]) -> dict[str, Any]:
    rec["source_system"] = "LegacyFTP"      # unknown source system
    return rec


def _inj_bad_datetime(rec: dict[str, Any]) -> dict[str, Any]:
    rec["synced_at"] = "2026-13-45 99:99"   # unparseable timestamp
    return rec


# Map: record index -> injector. Chosen indices are spread across sources.
_INJECTORS = {
    7: _inj_missing_required,
    13: _inj_null_violation,
    21: _inj_type_mismatch,
    34: _inj_range_low,
    48: _inj_range_high,
    59: _inj_bad_enum,
    66: _inj_bad_source,
    77: _inj_bad_datetime,
    88: _inj_missing_required,
    95: _inj_type_mismatch,
    101: _inj_null_violation,
    118: _inj_bad_enum,
}


def generate_feed(n_records: int = 140, seed: int = 42) -> list[dict[str, Any]]:
    """
    Produce a reproducible synthetic feed of `n_records` cost records across the
    configured source systems, with a fixed catalogue of injected defects.
    """
    rng = random.Random(seed)
    feed: list[dict[str, Any]] = []
    for idx in range(n_records):
        source = SOURCE_SYSTEMS[idx % len(SOURCE_SYSTEMS)]
        rec = _clean_record(rng, idx, source)
        injector = _INJECTORS.get(idx)
        if injector is not None:
            rec = injector(rec)
        feed.append(rec)
    return feed


def feed_as_json(n_records: int = 140, seed: int = 42, indent: int = 2) -> str:
    """Return the feed serialized exactly as an API payload would deliver it."""
    return json.dumps(generate_feed(n_records, seed), indent=indent)


if __name__ == "__main__":
    data = generate_feed()
    print(f"Generated {len(data)} synthetic records across "
          f"{len(SOURCE_SYSTEMS)} source systems (seed=42).")
    print("Injected defects at record indices:", sorted(_INJECTORS))
    print("\nSample record:")
    print(json.dumps(data[0], indent=2))
