# API Feed Schema & Integration-Health Monitor

A Streamlit dashboard that ingests a sample multi-source API/JSON feed, validates
it against an expected data-model schema, and visualizes integration health —
the kind of day-to-day work behind keeping a **unified API for construction data**
trustworthy as it fans out across many upstream source systems.

> **All data in this project is 100% synthetic.** It is generated locally by
> `data_gen.py` with a fixed random seed, and a known set of schema defects is
> injected on purpose so the validator has real issues to catch. No real company,
> project, vendor, or financial data is used anywhere.

---

## Why this project

A unified API sits between many source systems (Procore, Autodesk Build, Sage 300,
QuickBooks, Bluebeam, …) and the customers consuming the data. Each source maps its
own fields into a shared contract. When one mapping drifts — a field goes missing, a
number arrives as a string, a status uses an unexpected value, a connector stops
syncing — it silently corrupts everything downstream. This dashboard is a small,
honest model of how you'd **monitor that contract**: validate every record at
ingestion, find where failures concentrate, and surface stale connectors before a
customer does.

## Views

1. **Overview (KPIs)** — headline tiles: connected source systems, records ingested,
   schema-valid %, integration uptime, and open data issues, plus the mix of defect
   types driving the issue count.
2. **Schema validation** — checks the feed against the expected schema (missing
   fields, null violations, type mismatches, invalid enum values, out-of-range
   values, unparseable timestamps) and lists every violation with record, source,
   field, and detail.
3. **Source integration health** — records ingested and schema error rate per source
   system, so you can see errors are not spread evenly.
4. **Data freshness / sync lag** — hours since each source last synced (against a
   24-hour freshness threshold) plus typical created→synced lag.
5. **Feed & schema reference** — the expected data-model contract in full, and a
   sample of the raw synthetic JSON feed.

Every view ends with a **"So what →"** recommendation.

## Design

Charts follow Cole Nussbaumer Knaflic's *Storytelling with Data*: takeaway titles
that state the finding, decluttered axes (no chartjunk gridlines), direct value
labels instead of legends where possible, and restrained color — gray for context,
a single accent color reserved for the point each chart is making.

## Project structure

| File | Role |
|------|------|
| `app.py` | Multi-view Streamlit dashboard (UI only). |
| `analytics.py` | Framework-free validation & metric logic — no Streamlit import, fully unit-testable. |
| `data_gen.py` | Synthetic feed generator (fixed seed) + the expected-schema definition. |
| `test_analytics.py` | Pytest unit tests for the validation and metric logic. |
| `requirements.txt` | Dependencies. |

Keeping the compute in `analytics.py` (separate from the Streamlit UI) is deliberate:
the validation rules are the part worth testing, and they're tested without spinning
up a web framework.

## Run it locally

```bash
# 1. (optional) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. launch the dashboard
streamlit run app.py
```

Peek at the raw synthetic feed, or run the tests:

```bash
python data_gen.py      # prints a summary + a sample record
pytest -q               # runs the unit tests
```

## Notes

- Deterministic by design: the fixed seed means the feed, the validation results,
  and every chart reproduce exactly on each run.
- The expected schema lives in `data_gen.EXPECTED_SCHEMA` and is rendered in full in
  the "Feed & schema reference" view.

---

**Author:** Leo Chan — [github.com/GoldenCrate](https://github.com/GoldenCrate)
