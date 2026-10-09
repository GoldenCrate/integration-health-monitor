"""
app.py
======
API Feed Schema & Integration-Health Monitor — a Streamlit dashboard that
ingests a synthetic multi-source API/JSON feed, validates it against an expected
data-model schema, and visualizes integration health.

All data is SYNTHETIC (see data_gen.py). Charts follow Cole Nussbaumer
Knaflic's "Storytelling with Data": takeaway titles, decluttered axes, direct
labels, and restrained, intentional use of color (gray = context, one accent
color = the point the chart is making).

Run:  streamlit run app.py
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import analytics as A
import data_gen

# --------------------------------------------------------------------------
# Palette — restrained by design. Gray for context, one accent for "look here".
# --------------------------------------------------------------------------
ACCENT = "#C7382F"      # problem / attention (muted brick red)
OK = "#2E7D59"          # healthy (muted green)
GRAY = "#B8BCC2"        # context / de-emphasized
INK = "#2B2F36"         # text

CATEGORY_LABELS = {
    A.MISSING_FIELD: "Missing field",
    A.NULL_VIOLATION: "Null violation",
    A.TYPE_MISMATCH: "Type mismatch",
    A.ENUM_VIOLATION: "Invalid enum value",
    A.RANGE_VIOLATION: "Out-of-range value",
    A.FORMAT_ERROR: "Bad timestamp format",
}

st.set_page_config(
    page_title="Integration-Health Monitor",
    page_icon="🔌",
    layout="wide",
)


# --------------------------------------------------------------------------
# Data loading (cached). Fixed seed => reproducible feed & results.
# --------------------------------------------------------------------------
@st.cache_data
def load_data():
    feed = data_gen.generate_feed()
    schema = data_gen.EXPECTED_SCHEMA
    now = data_gen.REFERENCE_NOW
    kpis = A.compute_kpis(feed, schema, now=now)
    violations = A.validate_feed(feed, schema)
    health = A.source_health(feed, schema)
    freshness = A.freshness_by_source(feed, now=now)
    return feed, schema, now, kpis, violations, health, freshness


feed, schema, NOW, kpis, violations, health, freshness = load_data()


def so_what(text: str) -> None:
    """Render a consistent 'So what / recommendation' callout per view."""
    st.markdown(
        f"""<div style="border-left:4px solid {ACCENT};background:#FBF3F2;
        padding:0.6rem 0.9rem;border-radius:4px;margin-top:0.5rem;">
        <span style="font-weight:700;color:{INK};">So what →</span>
        <span style="color:{INK};"> {text}</span></div>""",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Sidebar navigation
# --------------------------------------------------------------------------
st.sidebar.title("🔌 Integration-Health Monitor")
st.sidebar.caption("Synthetic unified-API feed · construction data")
view = st.sidebar.radio(
    "View",
    [
        "Overview (KPIs)",
        "Schema validation",
        "Source integration health",
        "Data freshness / sync lag",
        "Feed & schema reference",
    ],
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    "**100% synthetic data** — generated locally with a fixed seed. "
    "No real company, project, or financial data.\n\n"
    "Author: **Leo Chan** · [github.com/GoldenCrate](https://github.com/GoldenCrate)"
)


# ==========================================================================
# VIEW 1 — Overview / KPI tiles
# ==========================================================================
if view == "Overview (KPIs)":
    st.title("Integration health at a glance")
    st.caption(
        f"As of {NOW:%Y-%m-%d %H:%M UTC} · {kpis['records_ingested']} records "
        f"from {kpis['connected_sources']} connected source systems · synthetic demo"
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Connected sources", kpis["connected_sources"])
    c2.metric("Records ingested", f"{kpis['records_ingested']:,}")
    c3.metric(
        "Schema-valid",
        f"{kpis['schema_valid_pct']}%",
        delta=f"{kpis['invalid_records']} failing",
        delta_color="inverse",
    )
    c4.metric("Integration uptime", f"{kpis['integration_uptime_pct']}%")
    c5.metric(
        "Open data issues",
        kpis["open_issues"],
        delta="needs triage" if kpis["open_issues"] else "clear",
        delta_color="inverse",
    )

    st.markdown("---")

    # Issue mix — one chart that frames the whole problem.
    counts = A.violations_by_category(violations)
    mix = pd.DataFrame(
        [{"category": CATEGORY_LABELS.get(k, k), "count": v} for k, v in counts.items()]
    ).sort_values("count", ascending=False)

    st.subheader(f"{kpis['open_issues']} open issues are concentrated in a few defect types")
    if not mix.empty:
        chart = (
            alt.Chart(mix)
            .mark_bar(color=ACCENT)
            .encode(
                x=alt.X("count:Q", title=None, axis=alt.Axis(grid=False)),
                y=alt.Y("category:N", sort="-x", title=None),
                tooltip=["category", "count"],
            )
        )
        labels = chart.mark_text(align="left", dx=4, color=INK).encode(text="count:Q")
        st.altair_chart((chart + labels).properties(height=240), width="stretch")

    top_cat = mix.iloc[0]["category"] if not mix.empty else "n/a"
    so_what(
        f"Schema validity is {kpis['schema_valid_pct']}% with {kpis['open_issues']} "
        f"open issues; '{top_cat}' is the single largest defect type. Fix the top "
        "one or two defect classes at the source mapping and most failures clear at once."
    )


# ==========================================================================
# VIEW 2 — Schema validation
# ==========================================================================
elif view == "Schema validation":
    st.title("Schema validation")
    st.caption(
        "Each incoming record is checked against the expected data-model contract "
        "(see 'Feed & schema reference'). Synthetic demo."
    )

    valid_pct = kpis["schema_valid_pct"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Records checked", f"{kpis['records_ingested']:,}")
    c2.metric("Records passing", f"{kpis['valid_records']:,}")
    c3.metric("Total violations", kpis["open_issues"])

    counts = A.violations_by_category(violations)
    mix = pd.DataFrame(
        [{"category": CATEGORY_LABELS.get(k, k), "count": v} for k, v in counts.items()]
    ).sort_values("count", ascending=False)

    st.subheader("Violations by type")
    if not mix.empty:
        chart = (
            alt.Chart(mix)
            .mark_bar(color=ACCENT)
            .encode(
                x=alt.X("count:Q", title=None, axis=alt.Axis(grid=False)),
                y=alt.Y("category:N", sort="-x", title=None),
                tooltip=["category", "count"],
            )
        )
        labels = chart.mark_text(align="left", dx=4, color=INK).encode(text="count:Q")
        st.altair_chart((chart + labels).properties(height=240), width="stretch")

    st.subheader("Violation detail")
    cats = ["All"] + [CATEGORY_LABELS.get(c, c) for c in counts]
    pick = st.selectbox("Filter by type", cats)
    vdf = pd.DataFrame(violations)
    if not vdf.empty:
        vdf["type"] = vdf["category"].map(lambda c: CATEGORY_LABELS.get(c, c))
        show = vdf if pick == "All" else vdf[vdf["type"] == pick]
        st.dataframe(
            show[["row_index", "record_id", "source_system", "field", "type", "detail"]]
            .rename(columns={
                "row_index": "row", "record_id": "record", "source_system": "source"
            }),
            width="stretch", hide_index=True,
        )
    else:
        st.success("No schema violations found.")

    so_what(
        "Validation runs field-by-field for presence, null, type, enum, and range. "
        "Catching these at ingestion — before the unified API serves them downstream — "
        "keeps a single bad source mapping from silently corrupting every consumer."
    )


# ==========================================================================
# VIEW 3 — Source integration health
# ==========================================================================
elif view == "Source integration health":
    st.title("Integration health by source system")
    st.caption("Records ingested and schema error rate per upstream source. Synthetic demo.")

    hdf = pd.DataFrame(health)
    worst = hdf.iloc[0] if not hdf.empty else None

    st.subheader(
        f"{worst['source_system']} has the highest error rate ({worst['error_rate_pct']}%)"
        if worst is not None else "Source error rates"
    )

    # Color: accent only for the worst offender; everything else gray context.
    hdf["is_worst"] = hdf["source_system"] == (worst["source_system"] if worst is not None else "")
    bars = (
        alt.Chart(hdf)
        .mark_bar()
        .encode(
            x=alt.X("error_rate_pct:Q", title="Error rate (%)", axis=alt.Axis(grid=False)),
            y=alt.Y("source_system:N", sort="-x", title=None),
            color=alt.condition(
                alt.datum.is_worst, alt.value(ACCENT), alt.value(GRAY)
            ),
            tooltip=["source_system", "records", "error_records", "error_rate_pct"],
        )
    )
    labels = bars.mark_text(align="left", dx=4, color=INK).encode(
        text=alt.Text("error_rate_pct:Q", format=".1f")
    )
    st.altair_chart((bars + labels).properties(height=260), width="stretch")

    st.subheader("Volume vs. errors by source")
    st.dataframe(
        hdf[["source_system", "records", "error_records", "error_rate_pct"]].rename(
            columns={
                "source_system": "source", "records": "records ingested",
                "error_records": "records with issues", "error_rate_pct": "error rate %",
            }
        ),
        width="stretch", hide_index=True,
    )

    if worst is not None:
        so_what(
            f"Errors are not spread evenly — {worst['source_system']} drives the highest "
            f"failure rate ({worst['error_rate_pct']}%). Prioritize a mapping review of that "
            "one connector rather than a blanket data-quality effort across all sources."
        )


# ==========================================================================
# VIEW 4 — Data freshness / sync lag
# ==========================================================================
elif view == "Data freshness / sync lag":
    st.title("Data freshness & sync lag")
    st.caption(
        f"How current each source is as of {NOW:%Y-%m-%d %H:%M UTC}, and typical "
        "created→synced lag. Synthetic demo."
    )

    fdf = pd.DataFrame(freshness)
    stale = fdf[fdf["is_stale"]] if not fdf.empty else fdf
    n_stale = len(stale)

    st.subheader(
        f"{n_stale} of {len(fdf)} sources are stale (last sync > 24h ago)"
        if n_stale else "All sources synced within the last 24 hours"
    )

    bars = (
        alt.Chart(fdf)
        .mark_bar()
        .encode(
            x=alt.X("hours_since_sync:Q", title="Hours since last sync",
                    axis=alt.Axis(grid=False)),
            y=alt.Y("source_system:N", sort="-x", title=None),
            color=alt.condition(alt.datum.is_stale, alt.value(ACCENT), alt.value(OK)),
            tooltip=["source_system", "hours_since_sync", "median_lag_min", "last_sync"],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"t": [24]}))
        .mark_rule(color=INK, strokeDash=[4, 4])
        .encode(x="t:Q")
    )
    labels = bars.mark_text(align="left", dx=4, color=INK).encode(
        text=alt.Text("hours_since_sync:Q", format=".1f")
    )
    st.altair_chart((bars + labels + rule).properties(height=260), width="stretch")
    st.caption("Dashed line = 24-hour freshness threshold.")

    st.subheader("Typical sync lag (created → synced)")
    st.dataframe(
        fdf[["source_system", "median_lag_min", "hours_since_sync", "is_stale", "last_sync"]]
        .rename(columns={
            "source_system": "source", "median_lag_min": "median lag (min)",
            "hours_since_sync": "hours since sync", "is_stale": "stale?",
            "last_sync": "last sync",
        }),
        width="stretch", hide_index=True,
    )

    so_what(
        "Sources that batch overnight drift stale and serve old numbers through the API. "
        "Track hours-since-sync against an SLA per source and alert when a connector "
        "crosses it, so freshness problems surface before a customer notices."
        if n_stale else
        "All sources are current. Keep the hours-since-sync SLA alert in place so a "
        "silently stalled connector is caught the moment it drifts past threshold."
    )


# ==========================================================================
# VIEW 5 — Feed & schema reference
# ==========================================================================
else:
    st.title("Feed & schema reference")
    st.caption("The expected data-model contract and a sample of the raw synthetic feed.")

    st.subheader("Expected schema (the contract every record must satisfy)")
    schema_rows = []
    for field, rule in schema.items():
        schema_rows.append({
            "field": field,
            "type": rule["type"],
            "required": rule.get("required", False),
            "nullable": rule.get("nullable", False),
            "allowed values / range": (
                ", ".join(map(str, rule["enum"])) if "enum" in rule
                else (f"{rule.get('min')} – {rule.get('max')}"
                      if "min" in rule or "max" in rule else "—")
            ),
        })
    st.dataframe(pd.DataFrame(schema_rows), width="stretch", hide_index=True)

    st.subheader("Sample raw feed (as the API would deliver it)")
    st.code(data_gen.feed_as_json(n_records=4), language="json")

    st.info(
        "This feed is generated locally by `data_gen.py` with a fixed seed, and a known "
        "set of defects is injected on purpose so the validator has real issues to catch. "
        "Nothing here is real data."
    )
    so_what(
        "A documented, machine-checkable schema contract is what makes a unified API "
        "trustworthy: every source is held to the same shape, and drift is caught "
        "automatically instead of by a downstream customer."
    )
