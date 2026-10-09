"""
test_analytics.py
=================
Unit tests for the framework-free validation/metric logic in analytics.py.
Run with:  pytest -q
"""

from __future__ import annotations

from datetime import datetime, timezone

import analytics as A
import data_gen


SCHEMA = data_gen.EXPECTED_SCHEMA


def _good_record() -> dict:
    return {
        "record_id": "REC-00001",
        "source_system": "Procore",
        "project_id": "PRJ-1001",
        "amount": 1250.5,
        "currency": "USD",
        "status": "approved",
        "cost_code": "03-1000",
        "vendor_name": None,          # nullable -> allowed
        "created_at": "2026-10-01T08:00:00+00:00",
        "synced_at": "2026-10-01T08:10:00+00:00",
    }


# ----------------------------- record validation ---------------------------
def test_clean_record_has_no_violations():
    assert A.validate_record(_good_record(), SCHEMA) == []


def test_missing_required_field():
    rec = _good_record()
    del rec["cost_code"]
    cats = {v["category"] for v in A.validate_record(rec, SCHEMA)}
    assert A.MISSING_FIELD in cats


def test_missing_optional_field_is_ok():
    rec = _good_record()
    del rec["vendor_name"]            # optional
    assert A.validate_record(rec, SCHEMA) == []


def test_null_in_non_nullable_field():
    rec = _good_record()
    rec["project_id"] = None
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.NULL_VIOLATION and x["field"] == "project_id" for x in v)


def test_null_in_nullable_field_is_ok():
    rec = _good_record()
    rec["vendor_name"] = None
    assert A.validate_record(rec, SCHEMA) == []


def test_type_mismatch_number_as_string():
    rec = _good_record()
    rec["amount"] = "1,250.00"
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.TYPE_MISMATCH and x["field"] == "amount" for x in v)


def test_bool_is_not_a_number():
    rec = _good_record()
    rec["amount"] = True
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.TYPE_MISMATCH for x in v)


def test_range_below_min():
    rec = _good_record()
    rec["amount"] = -5.0
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.RANGE_VIOLATION for x in v)


def test_range_above_max():
    rec = _good_record()
    rec["amount"] = 99_000_000.0
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.RANGE_VIOLATION for x in v)


def test_enum_violation_status():
    rec = _good_record()
    rec["status"] = "APPROVED!"
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.ENUM_VIOLATION and x["field"] == "status" for x in v)


def test_enum_violation_unknown_source():
    rec = _good_record()
    rec["source_system"] = "LegacyFTP"
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.ENUM_VIOLATION and x["field"] == "source_system" for x in v)


def test_bad_datetime_is_format_error():
    rec = _good_record()
    rec["synced_at"] = "2026-13-45 99:99"
    v = A.validate_record(rec, SCHEMA)
    assert any(x["category"] == A.FORMAT_ERROR and x["field"] == "synced_at" for x in v)


# ----------------------------- datetime helper ------------------------------
def test_parse_datetime_valid_and_invalid():
    assert A.parse_datetime("2026-10-01T08:00:00+00:00") is not None
    assert A.parse_datetime("not-a-date") is None
    assert A.parse_datetime(None) is None
    assert A.parse_datetime(123) is None


def test_parse_datetime_assumes_utc_when_naive():
    dt = A.parse_datetime("2026-10-01T08:00:00")
    assert dt is not None and dt.tzinfo is not None


def test_sync_lag_minutes():
    rec = _good_record()                 # 08:00 -> 08:10
    assert A.sync_lag_minutes(rec) == 10.0
    rec["synced_at"] = "bad"
    assert A.sync_lag_minutes(rec) is None


# ----------------------------- feed-level roll-ups --------------------------
def test_validate_feed_tags_row_and_source():
    feed = [_good_record(), {**_good_record(), "status": "nope"}]
    violations = A.validate_feed(feed, SCHEMA)
    assert all("row_index" in v and "source_system" in v for v in violations)
    assert {v["row_index"] for v in violations} == {1}


def test_generated_feed_has_expected_defect_count():
    feed = data_gen.generate_feed()
    bad = A.invalid_row_indices(feed, SCHEMA)
    # The generator injects defects at a known, fixed set of row indices.
    assert bad == set(data_gen._INJECTORS.keys())


def test_compute_kpis_shape_and_values():
    feed = data_gen.generate_feed()
    k = A.compute_kpis(feed, SCHEMA, now=data_gen.REFERENCE_NOW)
    assert k["records_ingested"] == len(feed)
    assert k["connected_sources"] == len(data_gen.SOURCE_SYSTEMS)
    assert 0.0 <= k["schema_valid_pct"] <= 100.0
    assert k["valid_records"] + k["invalid_records"] == len(feed)
    assert k["open_issues"] >= k["invalid_records"]  # a row can hold >1 issue


def test_source_health_sums_to_feed():
    feed = data_gen.generate_feed()
    rows = A.source_health(feed, SCHEMA)
    assert sum(r["records"] for r in rows) == len(feed)
    for r in rows:
        assert 0.0 <= r["error_rate_pct"] <= 100.0


def test_freshness_flags_stale_batch_source():
    feed = data_gen.generate_feed()
    fresh = A.freshness_by_source(feed, now=data_gen.REFERENCE_NOW,
                                  stale_threshold_hours=24.0)
    assert {r["source_system"] for r in fresh} >= set(data_gen.SOURCE_SYSTEMS)
    for r in fresh:
        assert "is_stale" in r


def test_violations_by_category_counts():
    feed = data_gen.generate_feed()
    counts = A.violations_by_category(A.validate_feed(feed, SCHEMA))
    assert sum(counts.values()) == len(A.validate_feed(feed, SCHEMA))
    assert A.MISSING_FIELD in counts  # generator injects missing fields


def test_median_helper():
    assert A._median([]) is None
    assert A._median([5]) == 5
    assert A._median([1, 3]) == 2.0
    assert A._median([1, 2, 3]) == 2
