# Output samples

### `analytics.json`, `metrics.csv`, `posts.csv`, `unavailable_metrics_report.{md,json}`

Produced by `tests/test_pipeline_offline.py`, which runs **every section and every
report writer against the local HTML fixtures** in `tests/`.

> **These numbers are fixture values, not LinkedIn data.** They exist to show the
> exact output schema and the shape of the Unavailable Metrics Report. The
> fixtures deliberately omit some elements (four of five demographic dimensions,
> keyword counts, the Content "Impressions" card) so the report's
> reason/limitation classification is visible too. Note `run.company_url` and
> `run.WARNING` in `analytics.json`.

### `unavailable_metrics_report_session_missing.md`

A real run of `run_analytics.py` against
`https://www.linkedin.com/company/99269371/admin/analytics/updates/` with **no
authenticated session stored** — i.e. the honest failure mode: all 38 requested
metrics reported `not_accessible` with limitation `session_expired`, nothing
estimated or invented. Exit code 2.

The sample run requests the **2026 calendar year** (`date_range: year_2026`),
drives the fixture's custom-range picker, and verifies the applied window —
see `date_window_requested` / `date_range_verified` in the JSON and the report
header.

Reproduce:

```bash
.venv/bin/python tests/test_pipeline_offline.py        # fixture-derived samples
.venv/bin/python run_analytics.py                      # real run (needs login.py first)
```
