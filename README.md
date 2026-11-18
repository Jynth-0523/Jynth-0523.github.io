# Factor Discovery Research Platform

A browser-based platform for systematic factor discovery, statistical validation,
and auditable research operations. Users bring their own panel, audit its structure,
generate bounded candidate formulas, and inspect frozen-model validation evidence.

**[Open the platform](https://jynth-0523.github.io/)**

This repository contains the English, portable source release prepared on
17 November 2026 from the local automation platform, plus its historical database,
health-check, and Tableau integrations. The separate four-algorithm paper project
is outside this repository. The existing GitHub Pages entry point is retained.

## Try it with a ready-to-use CSV

**[Download the example CSV (13.5 MB)](https://raw.githubusercontent.com/Jynth-0523/Jynth-0523.github.io/main/examples/factor-discovery-daily-example-1990-2025.csv)**
· [View the file in this repository](examples/factor-discovery-daily-example-1990-2025.csv)

The live website already offers this file under
[Example data → Download example CSV](https://factor-discovery-research.xu001258.chatgpt.site/#example-data).
This repository copy was downloaded unchanged from that button on 17 November 2026.
It contains **187,860 rows, 20 synthetic assets, 9,393 weekday dates, and four
candidate features**, spanning **1990-01-01 through 2025-12-31**. Its weekday calendar
is illustrative, not an exchange-holiday calendar.

1. Save the linked file as `.csv`. If your browser displays the raw text, use
   **Save As** to download it.
2. Open the [discovery workspace](https://factor-discovery-research.xu001258.chatgpt.site/discover)
   and choose the downloaded CSV.
3. Check the field mapping and settings below. Keep the observations **Daily**;
   the target is a **21-period forward return**, not a one-day return.
4. Run the data audit, then run discovery after it passes. Review any validation
   failures and export your own run evidence; a passing data audit is not a
   successful investment strategy.

| Workspace setting | Value |
| --- | --- |
| Entity identifier | `asset_id` |
| Observation date | `date` |
| Feature availability date | `available_date` |
| Forward return target | `forward_return_21d` |
| Data frequency | Daily |
| Target horizon | 21 daily periods |
| Candidate features | `value`, `quality`, `momentum_1m`, `volatility_1m` |

Returns use decimal units: `0.01` means 1%. Do not include the return target or the
date columns among candidate features. On the hosted workspace, portfolio
rebalancing frequency is a separate setting; it does not change the input frequency
or the target horizon.

**Synthetic example only:** these are artificial values for learning the upload
format and workflow. They contain no licensed observations and are not the historical
research sample, author-replication data, or evidence of empirical accuracy. Availability
dates are synthetic too. The hosted site and this source snapshot evolve separately;
the bundled local sample-download component still generates its older monthly demo.
The daily CSV linked here passes the bundled worker's import and data audit with
the mapping above. No discovery result or research replication was rerun for this addition.

## Technology and responsibilities

| Technology | Implemented responsibility | Source |
| --- | --- | --- |
| Python | Configuration validation; single-instance jobs; timeouts and bounded retry; hash-linked run records; alerts; health-check schemas; human candidate review; constrained AI explanation and proposal adapters | `backend/src/research_platform/` |
| JavaScript / TypeScript, React | User interface, local CSV/ZIP ingestion, data audit, bounded formula generation, browser-worker evaluation, chronological validation, and downloadable evidence | `web/app/` |
| PostgreSQL | Historical immutable research runs, window records, frozen factor weights, validation candidates, artifact identities, and four Tableau-facing read-only views | `database/` |
| Tableau | Historical Live Connection dashboard: deployment decisions, confidence, frozen weights, factor screening, and separate Formal/Shadow OOS panels | `tableau/` |

The web language is **JavaScript/TypeScript**. No Java implementation was found in
the platform source. The browser workspace does not need PostgreSQL or Tableau;
these support the historical research archive and reporting workflow.

## What the browser workspace does

- Accepts a local panel with entity, observation date, forward return, and 2–50
  numeric features. CSV or a ZIP containing one CSV is supported, subject to
  explicit row, file-size, memory, and workload limits.
- Audits duplicate entity-date keys, coverage, chronology, return scale, and
  point-in-time availability when supplied. Without availability metadata,
  historical information timing cannot be independently established.
- Uses chronological Train, Selection, and Calibration stages with horizon-aware
  purges, HAC uncertainty estimates, and joint Holm–Bonferroni correction.
- Supports bounded lag, change, rolling, nonlinear, and interaction operators;
  preserves missing history and checks available frozen weight when scoring.
- Evaluates frequency-aware annual deployment blocks, turnover, and configured
  transaction-cost scenarios. Failed Calibration blocks remain cash/no-trade.
- Exports research JSON, factor-definition CSV, walk-forward CSV, and a validation
  report from the same in-browser result. User panels are not uploaded to the backend.

Optional browser AI may download model assets. The Python AI adapters are separate,
optional integrations; their schemas and deterministic checks constrain authority.

## Run on another computer

Prerequisites: Python 3.11+ for the backend; Node.js **22.13+** and npm for the web.
The application has no author-specific absolute paths. `.env.example` documents
optional environment settings; it is not loaded automatically.

```sh
git clone https://github.com/Jynth-0523/Jynth-0523.github.io.git
cd Jynth-0523.github.io
python3 -m pip install -r backend/requirements.txt
cd web
npm ci
npm run dev
```

Open `http://localhost:3000`. The default browser workspace starts without the
private V8 research runner, local AI server, PostgreSQL, or proprietary datasets.
The existing `index.html` is the GitHub Pages link to the hosted application;
committing this source does not itself redeploy that hosted application.

## Verification

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src python3 -B -m unittest discover -s backend/tests -v
cd web
npm test
```

Python tests use synthetic fixtures and stubbed services. Browser-worker tests use
synthetic panels. Rendered-page tests run against the production build. See
[`docs/validation.json`](docs/validation.json) for the checks actually executed for
this release. A software-test pass rate is not a literature replication accuracy.

## Evidence and replication claims

The platform implements research procedures and exposes their evidence. Its source
does **not** contain a paper-by-paper benchmark that establishes how many published
empirical conclusions were successfully replicated, nor an aggregate replication
accuracy percentage. Those two metrics are **not established** and are not claimed.

The earlier project literature review documented 72 evidence objects and 68 unique
primary versions. These are review-coverage counts, not successful replications.
Methodological references, a passing software test, and a successful calibration
gate measure different things; none establishes reproduction of a paper's data or
economic conclusions. See [`docs/evidence_scope.md`](docs/evidence_scope.md).

The existing web snapshot (`web/app/platform-data.ts`) records historical development
facts: 1,000 generated candidates, 899 passing training hygiene, a 100-candidate
stability shortlist, and one 30-component ensemble (25 positive weights and 5 zero
weights). Its calibration confidence is 0.676511, but the later cost-aware gate is
recorded as **FAILED** and `finalModelCreated` is **false**. These are stored snapshot
values carried into this source release, not newly rerun or independently reproduced
results. The components are not 30 separately validated strategies.

The historical V3.1.2 reporting identity is 23 windows by 72 columns: 14 deployed
Formal OOS windows and 9 Shadow-only diagnostic windows. Formal and Shadow remain
mutually exclusive, and unavailable observations remain NULL. These historical
counts are not an accuracy or profitability guarantee.

## Optional historical integrations

`backend/config/platform_config.json` locates the bundled health-check launcher
relative to the repository and verifies its hash. To inspect your own authorized
copy of the locked historical archive, export `RESEARCH_ASSETS_ROOT`,
`LOCKED_RESEARCH_ROOT`, `PGHOST`, `PGPORT`, `PGDATABASE`, and `PGUSER`, using the layout
in `health_check/health_check_config.json`. Use local PostgreSQL authentication.
Do not put passwords in source files or command-line arguments.

`database/import_locked_run.py` is an explicit administrative importer for a
separate authorized database. It is not called by the platform, tests, or startup.
Do not reimport or overwrite an existing immutable run. Read-only verification is
available in `database/verify_locked_run.sql`.

`tableau/research_dashboard_template.twb` is a sanitized derivative of the historical
workbook. Set your own PostgreSQL connection and authentication in Tableau. It
requires the four `v312.tableau_*` views; no extract, database dump, password, or
licensed row-level data is included. Its published hash differs from the locked
original because the connection username was removed.

The optional Python V8 discovery endpoint requires a separately restored project
specified by `DISCOVERY_ENGINE_ROOT`, matching the frozen hashes in
`backend/config/discovery_config.json`. Set `PLATFORM_PYTHON` if a particular interpreter
is needed, and `ENABLE_LOCAL_DISCOVERY_API=1` only after configuring that integration.
The frozen private V8 runner was not found in the inspected platform folders.

## Repository map

| Directory | Contents |
| --- | --- |
| `backend/` | Python platform, schemas, portable configuration, tests, operational documentation |
| `web/` | React application, TypeScript worker, build scripts, tests, public assets |
| `health_check/` | English read-only historical-asset verifier and environment-based configuration |
| `database/` | PostgreSQL importer, read-only verification SQL, optional dependencies |
| `tableau/` | Sanitized Live Connection workbook template |
| `examples/` | Ready-to-upload synthetic daily CSV copied from the live website |
| `docs/` | Per-file inventory, provenance hashes, evidence scope, release verification |

See [`docs/file_inventory.md`](docs/file_inventory.md) for every published file and
[`docs/source_manifest.json`](docs/source_manifest.json) for source-to-release
mapping and hashes. Files and package directories are named for their purpose,
not a release number. Statistics, candidate formulas, portfolio evidence, charts,
exports, and historical asset checks are separate modules. Historical research
IDs, database schema names, and locked archive references retain their original
identities for compatibility; they are not publication filenames. Dependency
lockfiles, Tableau XML, and the generated browser-worker bundle are machine
artifacts rather than large hand-maintained source modules.

Raw CRSP/Compustat/CCM data, database dumps, historical result archives, credentials,
machine-specific hosting identity, and the four-algorithm paper code are excluded.
Access to this repository does not grant a license to redistribute vendor data.
