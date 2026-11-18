# Factor Discovery — Public Research Release

This page provides a professional public interface for factor discovery. Users
can select a CSV panel, map entity/date/forward-return/feature columns, pass a
local data audit, and run candidate generation, Train screening, correlation
pruning, Selection, and Calibration entirely in a browser worker. The audit
checks stable-key uniqueness, completeness, frequency-aware coverage, target scale,
and—when supplied—a point-in-time availability date. Users also declare the
forward-return horizon. Discovery uses horizon-aware purge boundaries, HAC
standard errors, a joint Holm–Bonferroni family, and a top-minus-bottom 20%
portfolio reported both gross and net of the selected transaction-cost
assumption. Uploaded panels may be daily, weekly, monthly, or quarterly; the
engine auto-detects the interval and allows a manual override. Every frequency
has its own Train/Selection/Calibration windows, return-horizon menu, purge
length, and full-year test block (252 daily, 52 weekly, 12 monthly, or 4
quarterly observations). Each selected model is frozen for one complete year.
It uses every complete block that fits an explicit
walk-forward observation budget and reports any resource-driven truncation.
Calibration failures hold cash for the full block, and net results include
entries, rebalances, and exits. CSV input is scanned incrementally; only mapped columns are retained
in a column-oriented working set. The file never leaves the device.
The homepage keeps synthetic example data separate from the user discovery workspace.

It intentionally has:

- one private bring-your-own-data browser workspace with no server upload;
- CSV support up to 200 MB and 500,000 rows, with 2–50 numeric features;
- a 640 MB estimated working-set guard and a bounded candidate-observation budget;
- a mandatory data-audit gate before discovery, with an explicit warning when
  no availability date is supplied and look-ahead safety cannot be independently verified;
- purged Train/Selection/Calibration boundaries, HAC inference, joint Holm
  correction, portfolio turnover, and 0/10/25/50 bps transaction-cost scenarios;
- frequency-aware train/selection/calibration/full-year-test evidence using a pre-fixed candidate dictionary,
  with all affordable complete blocks evaluated in the browser;
- cumulative gross/net wealth and RankIC traces, a seven-gate decision ledger,
  and a full-year block ledger backed by observations at the selected frequency;
- local exports for the complete research JSON, frozen factor definitions,
  walk-forward evidence, and a readable validation report;
- a directly downloadable browser engine and research-method note;
- no mutable research parameters, review actions, or database writes;
- optional private in-browser AI proposals, with deterministic validation still mandatory;
- no claim that the 30 components are independently validated strategies;
- an explicit distinction between development evidence and untouched Formal evaluation;
- complete Train diagnostics and frozen weights for all registered components.

The public snapshot is defined in `app/platform-data.ts`. It contains only
verified stored development facts, including the later failed cost-aware gate and
the absence of a final model. User datasets and generated private results remain
ephemeral and are not added to the public registry.

## Verification

```text
pnpm run build
node --test tests/rendered-html.test.mjs
```

The rendered-page test rejects free-form inputs, candidate-review APIs, and
operator controls. It verifies the runnable discovery workspace, English
public-release framing, and professional interpretation and limitation notes.
