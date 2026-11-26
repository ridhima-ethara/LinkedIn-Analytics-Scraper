# LinkedIn Page Analytics Extractor — Playwright + Firefox

Extracts LinkedIn **Company Page admin analytics** (Overview, Content, Visitors,
Life page, Followers, Search appearances, individual post analytics and video
metrics) into JSON + CSV, and produces an **Extracted vs Unavailable report**
that states, per metric, exactly why anything is missing.

Built with **Python + Playwright (Firefox)**. No Selenium, no Chromium.

> **Authentication policy.** The tool never types credentials, never automates a
> login form and never attempts to bypass LinkedIn authentication, access
> control or security checks. A human signs in once (including MFA) in a visible
> Firefox window; only the resulting session state is persisted, encrypted at
> rest. If a metric is not reachable through the authenticated admin UI, it is
> reported as unavailable with a reason — never estimated, inferred or invented.

---

## 1. Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install firefox      # Linux: add --with-deps
cp .env.example .env                                # optional
```

Python 3.10+ (tested on 3.13). For EC2 see **EC2_SETUP.md**.

## 2. Authenticate once

```bash
.venv/bin/python login.py            # opens Firefox; you log in + MFA by hand
.venv/bin/python login.py --check    # validate the stored session, headless
.venv/bin/python login.py --clear    # forget the stored session
```

The session is written to `secrets/linkedin_state.json.enc`, encrypted with a
Fernet key taken from `$LI_SESSION_KEY` or, if unset, generated into
`secrets/session.key` (chmod 600). `secrets/` is git-ignored.

On a server with no display, see the `--from-cookie-env` path in **EC2_SETUP.md**.

## 3. Run

```bash
.venv/bin/python run_analytics.py                       # URL + window from config.yaml
.venv/bin/python run_analytics.py --url https://www.linkedin.com/company/<id>/admin/analytics/updates/
.venv/bin/python run_analytics.py --year 2026                # calendar year 2026
.venv/bin/python run_analytics.py --start 2026-01-01 --end 2026-06-30
.venv/bin/python run_analytics.py --date-range past_90_days --max-posts 25
.venv/bin/python run_analytics.py --sections visitors,followers --headed
.venv/bin/python run_analytics.py --no-post-detail           # skip per-post pages
```

### Date windows

`config.yaml` ships with `extraction.date_range: year_2026`, i.e. 1 Jan 2026 →
today (a future end date is clamped, since LinkedIn cannot report on days that
have not happened). Accepted values:

| Value                                                                     | Window                                        |
| ------------------------------------------------------------------------- | --------------------------------------------- |
| `year_2026`                                                             | 1 Jan 2026 → 31 Dec 2026, clamped to today   |
| `custom` + `custom_start` / `custom_end`                            | explicit dates (`custom_end` blank = today) |
| `"2026-01-01..2026-06-30"`                                              | explicit inline window                        |
| `past_7_days` / `past_28_days` / `past_90_days` / `past_365_days` | rolling preset                                |
| `keep_default`                                                          | leave whatever the UI opens with              |

A calendar-year request is entered through LinkedIn's **Custom range** picker.
Because that is the part most likely to differ from one LinkedIn build to
another, the applied window is **read back from the UI and verified**:

* `run_meta.json` / the report header record `date_window_requested`,
  `date_range_applied` (the label LinkedIn displayed) and
  `date_range_verified` (`true`/`false`) plus the verification sentence.
* If the picker cannot be driven, the tool does **not** pretend: it notes the
  failure, falls back to the nearest rolling preset, labels the date range
  `… [requested 2026-01-01 .. 2026-11-25 — NOT CONFIRMED]`, and sets
  `date_range_verified: false`. Treat such a run as *not* the year you asked for.
* LinkedIn Page analytics supports **at most a 365-day window**; a longer request
  is flagged in the notes.

**Post-level metrics are not date-filterable.** LinkedIn reports each post's
impressions/engagement cumulatively since it was published. The window therefore
selects *which posts are opened* (`extraction.post_date_filter: true` keeps posts
published inside it; posts with an unparseable date are kept and flagged), and
each per-post metric records the range the post page itself displayed.

Any company page works — pass `--url` (or set `company.url`); the tool derives
all section URLs from the `/company/<id>/` part and also reads LinkedIn's own
analytics navigation at runtime, so a moved tab is followed automatically.

Exit codes: `0` run completed · `2` session missing/expired (run `login.py`) ·
`3` fatal error before any section ran.

## 4. Output

Everything lands in `output/<timestamp>_<companyId>/`:

| File                                          | Contents                                                                              |
| --------------------------------------------- | ------------------------------------------------------------------------------------- |
| `analytics.json`                            | run metadata, per-metric records, per-post records, section outcomes, discovered nav  |
| `metrics.csv`                               | one row per metric: name, value, date range, category, status, source section, reason |
| `posts.csv`                                 | one row per post: list-level + detail-level metrics incl. video                       |
| `unavailable_metrics_report.md` / `.json` | extracted / partial / not-accessible with exact reasons                               |
| `run_meta.json`                             | versions, date range, session state, timings                                          |
| `screenshots/`                              | one per section, plus a screenshot on every failure                                   |
| `page_text/`                                | rendered text of each section (verification evidence)                                 |
| `evidence/`                                 | parsed tables, demographics, per-post values, captured analytics XHR                  |

`logs/<run_id>.log` holds the full DEBUG log.

Sample outputs produced from local fixtures (not LinkedIn data) are in
`samples/` — see `samples/README.md`.

### Metric record fields

```
metric_name, value, raw_value, unit, date_range, category, status,
source_section, source_url, entity, limitation, reason, strategy,
evidence, extracted_at
```

* `status` — `extracted` | `partial` | `not_accessible`
* `limitation` — `none` | `linkedin_ui` | `permissions` | `data_unavailable` |
  `automation_failure` | `session_expired` | `not_attempted`
* `entity` — set for scoped rows: a post URN, or a demographic/keyword bucket
* `evidence` — the on-page text the value was read from, so any number can be
  checked against the UI by eye
* `strategy` — how it was found (e.g. `label-anchor:Impressions@depth2`)

## 5. Metric coverage

| Category                  | Metrics                                                                                                                                                                           | Source in the UI                                                                                                 |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Overview                  | Search Appearances, New Followers, Post Impressions, Page Visitors                                                                                                                | Analytics overview cards                                                                                         |
| Content                   | Impressions, Reactions, Comments, Reposts                                                                                                                                         | Content tab highlight cards                                                                                      |
| Visitors                  | Page Views, Unique Visitors, Custom Button Clicks                                                                                                                                 | Visitors tab cards                                                                                               |
| Visitors → Demographics  | Job Function, Company Size, Industry, Location, Seniority                                                                                                                         | Visitor demographics module (selector is driven through all five dimensions)                                     |
| Life Page                 | Page Views, Unique Visitors, Last Updated                                                                                                                                         | Visitors → "Page views by page" → *Life page* row (LinkedIn gives the Life tab no analytics page of its own) |
| Followers                 | Total Followers, New Followers                                                                                                                                                    | Followers tab                                                                                                    |
| Search Appearance         | Page Searches, Top Keywords, Top Page Searcher Demographics                                                                                                                       | Search appearances tab                                                                                           |
| Individual Post Analytics | Impressions, Members Reached, Page Viewers from This Post, Followers Gained from This Post, Engagement, Engagement Rate, Clicks, Click Through Rate, Reactions, Comments, Reposts | each post's own analytics page                                                                                   |
| Video Posts               | Video Views, Watch Time, Average Watch Time                                                                                                                                       | post analytics page of video posts only                                                                          |

**Per-post rollups.** Each per-post metric is stored twice: a row per post
(`entity = urn:li:activity:…`) with the real value, and one catalog summary row
whose `value` is *the number of posts that yielded the metric* (`unit = posts`),
with every per-post value under `detail.per_post`. The summary deliberately does
not aggregate (summing impressions across posts would be a derived number, not
an extracted one).

**Breakdowns.** Demographics and keywords are stored as a summary row
(`value` = bucket count, `detail.buckets` = all buckets) plus one row per bucket
with `entity = <bucket label>`.

## 6. How extraction works

1. **Navigate** to each analytics tab (config override → derived URL → LinkedIn's
   own nav links → alternate paths), retrying with backoff.
2. **Settle** the page: `networkidle`, then incremental scrolling to force lazy
   charts/tables to hydrate, then a second idle wait.
3. **Apply the date filter** by clicking the real control, then read back the
   label LinkedIn displays — that label is what appears in the reports, so the
   date range is never assumed.
4. **Expand pagination** by clicking every *Show more* / *Load more* control until
   exhausted.
5. **Read values by label**, not by CSS class: find the element whose own text is
   the metric label, climb to the nearest ancestor that also contains a number,
   and take that number — after stripping comparison deltas (`▲ 12%`,
   `vs previous 28 days`). Class names in LinkedIn's admin UI are build-hashed
   and change without notice; visible labels do not.
6. **Parse tables and ARIA grids** structurally (headers → row dicts) for the
   post performance table and the page-views-by-page table.
7. **Classify failures**: LinkedIn's own empty-state text ("no data available",
   "not enough data") is detected so missing numbers are reported as
   `data_unavailable` rather than blamed on the automation; access/not-found
   pages become `permissions`; a login/checkpoint redirect becomes
   `session_expired`; anything else is `automation_failure`.
8. **Record evidence** for every run: screenshots, rendered page text, parsed
   tables, and the analytics XHR payloads the page itself fetched (passively
   observed; the tool issues no API calls of its own).

## 7. Tests (no LinkedIn access needed)

```bash
.venv/bin/python tests/test_heuristics.py        # label→value, tables, parsing
.venv/bin/python tests/test_pipeline_offline.py  # all sections + all reports
```

`tests/fixture_analytics.html` and `tests/fixture_post.html` mimic the admin
layout (cards with comparison deltas, page-views-by-page table, post table with
URNs, demographics module, empty states, video stats) with known-correct values,
so the parsing logic is verified independently of LinkedIn.

## 8. Configuration

`config.yaml` is the single source of defaults; CLI flags and `LIA_*` env vars
override it. Notable keys:

```yaml
company.url                     # page to extract
urls.*                          # pin a section URL if LinkedIn moves a tab
urls.post_summary_templates     # candidate URL patterns for a post's analytics
browser.headless / viewport / nav_timeout_ms / action_timeout_ms
session.storage_state_path / encrypt / key_env / key_file
extraction.date_range           # past_7_days | past_28_days | past_90_days |
                                # past_365_days | keep_default
extraction.max_posts            # posts opened for individual analytics
extraction.post_detail          # false = skip per-post pages
extraction.settle_ms / scroll_passes / expand_show_more_rounds
extraction.retries / retry_backoff_s
extraction.sections             # subset of sections to run
output.save_screenshots / save_page_text / save_raw_network
```

## 9. Known limitations

* **Admin role required.** Metrics only exist for Pages where the signed-in
  account is an admin; otherwise sections are reported `permissions`.
* **Life page "Last Updated"** is only available if LinkedIn renders a
  last-updated column in *Page views by page* for this Page; otherwise it is
  reported as a `linkedin_ui` limitation rather than guessed.
* **Keyword search counts** are often not published per keyword; in that case
  Top Keywords is reported `partial` with the keyword list captured.
* **Video watch time** is a formatted duration (`1h 23m`, `0:21`); it is stored
  verbatim as text with `unit=text`, not converted into seconds.
* **Date ranges** are limited to the presets LinkedIn offers in the UI; a preset
  the UI does not offer is noted and the page default is used (and reported).
* LinkedIn changes this UI frequently. When a label changes, add the new wording
  to `LABELS` in `src/catalog.py` — no other code change is needed.
