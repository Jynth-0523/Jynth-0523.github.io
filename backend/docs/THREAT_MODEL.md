# Phase 0 Threat Model

## Protected assets

- locked research source and tests;
- historical market, membership, primitive, and factor caches;
- the immutable PostgreSQL final run;
- permanent walk-forward archive and manifests;
- final report and Tableau workbook;
- Formal and Shadow OOS semantics, including null preservation.

## Trust boundaries

The deterministic platform policy and validators are trusted code. Health JSON,
subprocess output, logs, papers, web content, database error text, and future AI
responses are untrusted data. A model response can never authorize a command,
path, permission, retry, database operation, or research decision.

## Allowed effects

- execute one fixed, hash-verified, read-only health-check script;
- read the resulting health JSON;
- write envelopes, claims, locks, and control audit records only inside this
  platform's runtime directory.

## Denied effects

- importing or running `locked_research.py`;
- running walk-forward, research tests, SQL writes, or Tableau modifications;
- accepting shell commands, paths, or subprocess arguments from user/model text;
- merging Formal and Shadow values or replacing null with zero;
- exposing raw OOS sequences to an AI component;
- automatic repair, tuning, notification, or external state change.

## Failure policy

- deterministic inconsistency is FAIL and is not retried;
- missing dependencies, timeouts, and incomplete observations are BLOCKED and
  receive at most two bounded retries;
- malformed or stale health output is never guessed or repaired;
- AI unavailability can never alter deterministic health status;
- the kill switch prevents subprocess execution and records only a local audit
  event.

## Residual risks

The platform cannot prove upstream data correctness, undo human knowledge of
OOS results, eliminate all researcher discretion, or guarantee that the host OS
and local credential configuration are uncompromised. Those risks are disclosed
rather than converted into a false PASS.

