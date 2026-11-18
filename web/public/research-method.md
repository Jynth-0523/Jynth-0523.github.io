# Factor Discovery research contract

## Purpose

Factor Discovery accepts a user-supplied asset panel and searches for cross-sectional factor candidates. It reports research evidence, not investment advice or a guarantee of performance.

## Input

One row represents one asset at one observation date. A panel must include an entity identifier, an observation date, a forward-return target, and at least two numeric candidate features. A point-in-time availability date is optional but recommended. CSV and a ZIP containing exactly one CSV are accepted.

## Frequencies and horizons

- Daily: 1, 5, 21, 63, or 252 trading periods.
- Weekly: 1, 4, 13, 26, or 52 periods.
- Monthly: 1, 3, 6, or 12 periods.
- Quarterly: 1, 2, 4, or 8 periods.

The chosen horizon controls purge length and HAC lags. Train, Selection, Calibration, and full-year walk-forward windows scale with the selected frequency.

## Data audit

The browser checks mapped columns, unique entity-date keys, parseable dates, complete observations, cross-sectional size, temporal coverage, feature missingness, target scale, frequency continuity, and point-in-time availability when supplied.

## Discovery and validation

The engine creates a bounded deterministic candidate family from selected feature columns. Optional in-browser AI may propose additional bounded expressions, but it has no decision authority. Train screens candidates; Selection fixes signs and weights; Calibration evaluates the frozen specification. Reported inference uses horizon-aware purging, Newey-West/HAC standard errors, Holm multiplicity adjustment, top-minus-bottom portfolios, turnover, transaction costs, and frequency-aware full-year walk-forward blocks.

## Browser limits

- File size: 200 MB uncompressed CSV.
- Rows: 500,000.
- Columns: 200.
- Selected numeric features: 2 to 50.
- Estimated working memory guard: 640 MB.

## Privacy and verification

Uploaded observations are parsed and analysed in the browser and are not submitted to the site. The deployed browser engine is available at `/factor-discovery.worker.js`. Completed runs export full JSON, factor-definition CSV, walk-forward CSV, and a Markdown validation report.

## Interpretation boundary

A discovered expression is not automatically a validated factor. Failed gates remain visible. An external untouched holdout and independent replication are still required before making an investment-performance claim.
