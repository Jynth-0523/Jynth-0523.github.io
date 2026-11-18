# Research Automation Backend

## Portable source release (17 November 2026)

This directory is the English publication copy of the platform backend. Its tests
use synthetic fixtures, including the development discovery and registry fixtures.
They do not require the author's private data. Install `requirements.txt` first.
The public browser workspace runs independently in `../web`.

The optional historical development discovery subprocess requires a separately supplied,
hash-verified project at `DISCOVERY_ENGINE_ROOT`; its former local path is unavailable.
The original frozen implementation hashes remain unchanged. The default private
integration fails closed when those files are absent. Historical health checks
require the environment described in the root README and `.env.example`.

This project is the independent automation and governance layer for the locked
locked research run. It does **not** import or execute the research module, and
it has no write path to the research code, database, archive, report, or
Tableau workbook.

## Current delivery boundary

Implemented in Phase 0/1 and the local-only portion of Phase 2:

- locked health-result schema and locked research semantic invariants;
- PASS/FAIL/BLOCKED and adversarial golden fixtures;
- one allowlisted command (`locked_research_health_check`);
- single-instance execution, idempotency claims, timeout, and bounded retry;
- kill switch with a separate audit trail;
- immutable run envelopes linked by SHA-256;
- content-minimized observation provenance and tool traces;
- offline replay and fault-injection tests;
- PASS-silent local alert simulation with FAIL/BLOCKED severity;
- root-cause deduplication and auditable human acknowledgement.
- one fixed development-only discovery route with locked code hashes;
- an optional no-tool AI explanation of a minimized aggregate development discovery summary;
- a 30-component development discovery registry with persistent human KEEP/WATCH/REJECT review;
- a separate irreversible review freeze hash that never changes development discovery weights.
- a public bring-your-own-data workspace that performs private factor discovery
  inside the user's browser without uploading or retaining the CSV.
- a constrained open-source-AI candidate proposer that sees only untrusted
  feature labels, emits allowlisted structures, and is revalidated before use.

Not implemented:

- system scheduling and external notification adapters (remaining Phase 2);
- any AI tuning, approval, tool call, cross-run memory, or deployment action;
- any access from the AI layer to raw research data or held-out results.

## Candidate component review

The development discovery result contains one frozen score assembled from 30 correlation-pruned
components: 25 have non-zero weights and 5 have zero weights. They are not 30
independently calibrated strategies. The backend maintains a separate human
review record. Review labels are stored in one local state file under
`runtime/factor_registry/`; they never write into the development discovery artifacts or research
database. After all 30 components are reviewed, the decisions can be frozen
with a deterministic SHA-256 identity. The public website does not expose
these operator controls; it publishes only the verified read-only registry.

## Bring-your-own-data discovery

The public workspace accepts a user-selected CSV panel, lets the user map the
entity, date, forward-return, and candidate-feature columns, and runs candidate
generation, chronological Train/Selection/Calibration evaluation, correlation
pruning, and frozen-ensemble calibration in a browser worker. Before discovery,
a mandatory local audit checks entity-date uniqueness, complete-case and period
coverage, chronology, target scale, and optional point-in-time availability;
the user must also declare the forward-return horizon. The browser engine ports
the reusable locked research inference principles through horizon-aware purge boundaries,
HAC standard errors, and a joint Holm–Bonferroni family. It adds a public-panel
economic check using equal-weight top-minus-bottom 20% returns, realized
turnover, and a selectable transaction-cost assumption. It also runs annual
24-Train/3-Selection/3-Calibration/12-test blocks, with a horizon-length purge
at all three boundaries; each model is frozen for the following twelve months,
and failed Calibration blocks hold cash for the full year while entry, rebalance,
and exit costs remain in net returns. All complete annual blocks are used when
their estimated workload fits the dedicated walk-forward budget; otherwise the
latest affordable sequence is evaluated and the result is marked as truncated.
The candidate dictionary is fixed before these annual tests. The worker scans CSV
input in chunks and retains only mapped columns in a column-oriented working
set, with explicit memory and candidate-workload guards. The CSV and the private
result are not sent to this project's backend or added to the published development discovery
registry. The browser workflow is a separate discovery engine and does not
alter the locked research/development discovery research artifacts.

Browser discovery expands the bounded language with same-asset one-period
lags, changes, normalized growth, three-period rolling means and volatility,
signed nonlinear transforms, and two-feature interactions. Temporal operators
use only prior dated observations for the same entity. Missing history remains
missing, ensemble scores require at least half of frozen weight to be available,
and screening applies a fixed complexity penalty. AI-proposed structures are
tagged but receive no statistical privilege: they use the same candidate budget,
purges, multiplicity correction, costs, and annual walk-forward validation.

The private result page traces cumulative gross and net out-of-sample wealth,
month-level RankIC, annual deployment versus cash decisions, turnover, and every
professional validation gate with its exact pass/fail reason. A completed run
can be exported as the full research JSON, a frozen factor-definition CSV, a
walk-forward evidence CSV with cumulative wealth, and a Markdown validation
report. All four exports are created in the browser from the same result object.

## Optional AI explanation

The platform works normally without AI. Its internal explanation service
defaults to a local Ollama endpoint on IPv4 loopback with `qwen3:4b`. The public
website exposes no AI interface. The backend builds a fixed aggregate
allowlist, requests strict structured output with no tools, then maps evidence
and next actions to deterministic local text.

OpenAI remains an explicit optional fallback by setting `PLATFORM_AI_PROVIDER` to
`openai`. It uses `store: false`; its API key is never passed to the browser or
development discovery subprocess. `OPENAI_MODEL` may select only an allowlisted GPT-5.6 model.

The local `qwen3:4b` integration also exposes a separate candidate-proposal
contract. It receives feature IDs and untrusted display names only—never raw
values, targets, Calibration, walk-forward results, or held-out data. Output is
a strict schema with at most twelve allowlisted structures. Invalid feature
references, code-like operations, malformed unary/binary formulas, duplicates,
and decision-authority claims are rejected outside the model. The public browser
workflow does not call this service by default, preserving its local-data promise.

## Locked command

The only live command accepted by the runner is:

```text
locked_research_health_check
```

It resolves to the existing absolute script path recorded in
`config/platform_config.json`. The runner verifies the script SHA-256 before
execution and passes no user-provided shell arguments.

## Offline verification

```bash
./scripts/run_tests.sh
```

The test runner uses `python -B` and `PYTHONDONTWRITEBYTECODE=1`.

## Offline fixture replay

```bash
./scripts/platform-control replay tests/fixtures/pass.json
```

Fixture replay never invokes the locked health check.

## Live run (manual only in Phase 1)

```bash
./scripts/platform-control run-now
```

This is intentionally not scheduled yet. A live run can only call the existing
read-only health-check script. Runtime artifacts are written under `runtime/`
inside this project.

## Kill switch

```bash
./scripts/platform-control disable "maintenance"
./scripts/platform-control enable "maintenance complete"
```

When disabled, the health-check subprocess is not started.

## Local alert simulation

PASS is archived silently. FAIL is classified as CRITICAL and BLOCKED as
WARNING. Only a minimized local outbox item is created; nothing is sent over
the network. Repeated events with the same deterministic root-cause fingerprint
are deduplicated. A human ACK is recorded separately:

```bash
./scripts/platform-control ack <fingerprint> "reviewed"
```
