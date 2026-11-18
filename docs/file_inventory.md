# Published file inventory

File names describe responsibilities. Original names and hashes are retained only in the provenance manifest and locked external archive references.

| File | Purpose |
| --- | --- |
| [`.env.example`](../.env.example) | Optional local environment settings; no credentials. |
| [`.gitignore`](../.gitignore) | Exclude private data, local settings, dependencies, and runtime output. |
| [`README.md`](../README.md) | Overview, downloadable example and mapping, setup, technology responsibilities, and evidence boundaries. |
| [`backend/README.md`](../backend/README.md) | Component setup and operational documentation. |
| [`backend/config/discovery_config.json`](../backend/config/discovery_config.json) | Component configuration: discovery config. |
| [`backend/config/platform_config.json`](../backend/config/platform_config.json) | Component configuration: platform config. |
| [`backend/docs/PHASE_STATUS.md`](../backend/docs/PHASE_STATUS.md) | Historical implementation-phase status and remaining boundaries. |
| [`backend/docs/THREAT_MODEL.md`](../backend/docs/THREAT_MODEL.md) | Security boundaries and explicitly forbidden operations. |
| [`backend/pyproject.toml`](../backend/pyproject.toml) | Component configuration: pyproject. |
| [`backend/requirements.txt`](../backend/requirements.txt) | Python dependencies for this directory. |
| [`backend/schemas/health_status.schema.json`](../backend/schemas/health_status.schema.json) | Component configuration: health status schema. |
| [`backend/schemas/run_envelope.schema.json`](../backend/schemas/run_envelope.schema.json) | Component configuration: run envelope schema. |
| [`backend/scripts/platform-control`](../backend/scripts/platform-control) | Portable operator CLI launcher. |
| [`backend/scripts/run_tests.sh`](../backend/scripts/run_tests.sh) | Backend unit-test launcher. |
| [`backend/src/research_platform/__init__.py`](../backend/src/research_platform/__init__.py) | Python package metadata. |
| [`backend/src/research_platform/__main__.py`](../backend/src/research_platform/__main__.py) | Python module entry point. |
| [`backend/src/research_platform/ai_boundary.py`](../backend/src/research_platform/ai_boundary.py) | Minimized AI evidence allowlist and untrusted-text boundary. |
| [`backend/src/research_platform/ai_candidate_proposer.py`](../backend/src/research_platform/ai_candidate_proposer.py) | Constrained AI formula proposal schema and deterministic validation. |
| [`backend/src/research_platform/ai_explainer.py`](../backend/src/research_platform/ai_explainer.py) | No-tool structured AI explanation adapters and output validation. |
| [`backend/src/research_platform/alerts.py`](../backend/src/research_platform/alerts.py) | Local alerts, deduplication, and acknowledgement audit. |
| [`backend/src/research_platform/cli.py`](../backend/src/research_platform/cli.py) | Operator command-line interface. |
| [`backend/src/research_platform/config.py`](../backend/src/research_platform/config.py) | Configuration, permissions, and hash validation. |
| [`backend/src/research_platform/constants.py`](../backend/src/research_platform/constants.py) | Historical locked identities and permissions. |
| [`backend/src/research_platform/discovery_api.py`](../backend/src/research_platform/discovery_api.py) | Optional loopback API and hash-verified private discovery adapter. |
| [`backend/src/research_platform/factor_registry.py`](../backend/src/research_platform/factor_registry.py) | Frozen component registry and separate human review state. |
| [`backend/src/research_platform/health_schema.py`](../backend/src/research_platform/health_schema.py) | Health-output parsing and Formal/Shadow semantic validation. |
| [`backend/src/research_platform/lock.py`](../backend/src/research_platform/lock.py) | Single-instance file locking. |
| [`backend/src/research_platform/runner.py`](../backend/src/research_platform/runner.py) | Allowlisted jobs, timeouts, retries, and run envelopes. |
| [`backend/src/research_platform/store.py`](../backend/src/research_platform/store.py) | Immutable run records and hash-chain persistence. |
| [`backend/src/research_platform/util.py`](../backend/src/research_platform/util.py) | Atomic file operations and identity helpers. |
| [`backend/tests/fixtures/blocked.json`](../backend/tests/fixtures/blocked.json) | Synthetic health-schema fixture: blocked. |
| [`backend/tests/fixtures/corrupt.json`](../backend/tests/fixtures/corrupt.json) | Synthetic health-schema fixture: corrupt. |
| [`backend/tests/fixtures/duplicate_key_invalid.json`](../backend/tests/fixtures/duplicate_key_invalid.json) | Synthetic health-schema fixture: duplicate key invalid. |
| [`backend/tests/fixtures/fail.json`](../backend/tests/fixtures/fail.json) | Synthetic health-schema fixture: fail. |
| [`backend/tests/fixtures/injection_fail.json`](../backend/tests/fixtures/injection_fail.json) | Synthetic health-schema fixture: injection fail. |
| [`backend/tests/fixtures/null_semantics_invalid.json`](../backend/tests/fixtures/null_semantics_invalid.json) | Synthetic health-schema fixture: null semantics invalid. |
| [`backend/tests/fixtures/overlap_invalid.json`](../backend/tests/fixtures/overlap_invalid.json) | Synthetic health-schema fixture: overlap invalid. |
| [`backend/tests/fixtures/pass.json`](../backend/tests/fixtures/pass.json) | Synthetic health-schema fixture: pass. |
| [`backend/tests/synthetic_discovery.py`](../backend/tests/synthetic_discovery.py) | Temporary synthetic discovery artifacts; does not execute research. |
| [`backend/tests/test_ai_boundary.py`](../backend/tests/test_ai_boundary.py) | Automated checks: ai boundary. |
| [`backend/tests/test_ai_candidate_proposer.py`](../backend/tests/test_ai_candidate_proposer.py) | Automated checks: ai candidate proposer. |
| [`backend/tests/test_ai_explainer.py`](../backend/tests/test_ai_explainer.py) | Automated checks: ai explainer. |
| [`backend/tests/test_alerts.py`](../backend/tests/test_alerts.py) | Automated checks: alerts. |
| [`backend/tests/test_config.py`](../backend/tests/test_config.py) | Automated checks: config. |
| [`backend/tests/test_discovery_api.py`](../backend/tests/test_discovery_api.py) | Automated checks: discovery api. |
| [`backend/tests/test_factor_registry.py`](../backend/tests/test_factor_registry.py) | Automated checks: factor registry. |
| [`backend/tests/test_health_schema.py`](../backend/tests/test_health_schema.py) | Automated checks: health schema. |
| [`backend/tests/test_portable_release.py`](../backend/tests/test_portable_release.py) | Automated checks: portable release. |
| [`backend/tests/test_runner.py`](../backend/tests/test_runner.py) | Automated checks: runner. |
| [`backend/tests/test_store_and_lock.py`](../backend/tests/test_store_and_lock.py) | Automated checks: store and lock. |
| [`database/import_locked_run.py`](../database/import_locked_run.py) | Explicit administrative importer for an authorized historical archive. |
| [`database/requirements.txt`](../database/requirements.txt) | Python dependencies for this directory. |
| [`database/verify_locked_run.sql`](../database/verify_locked_run.sql) | Read-only SQL verification of historical invariants. |
| [`docs/evidence_scope.md`](../docs/evidence_scope.md) | What software, literature, and historical evidence can establish. |
| [`docs/file_inventory.md`](../docs/file_inventory.md) | This per-file purpose index. |
| [`docs/release_manifest.json`](../docs/release_manifest.json) | Published-file sizes and SHA-256 hashes; excludes its own self-hash. |
| [`docs/source_manifest.json`](../docs/source_manifest.json) | Original-to-published provenance, extraction mapping, and SHA-256 hashes. |
| [`docs/validation.json`](../docs/validation.json) | Executed verification checks and untested integration boundaries. |
| [`examples/factor-discovery-daily-example-1990-2025.csv`](../examples/factor-discovery-daily-example-1990-2025.csv) | Unchanged synthetic daily sample from the live website: 20 assets, 187,860 rows, 1990–2025. |
| [`health_check/audit_archive.py`](../health_check/audit_archive.py) | Locked archive and canonical report checks. |
| [`health_check/audit_common.py`](../health_check/audit_common.py) | Read-only file hashes, safe paths, snapshots, and evidence recorder. |
| [`health_check/audit_database.py`](../health_check/audit_database.py) | Read-only PostgreSQL invariants and view checks. |
| [`health_check/audit_reports.py`](../health_check/audit_reports.py) | Report package, protected source, and database-dump identity checks. |
| [`health_check/audit_tableau.py`](../health_check/audit_tableau.py) | Historical Tableau artifact and validation-evidence checks. |
| [`health_check/check_research_assets.py`](../health_check/check_research_assets.py) | Environment validation, safety snapshots, and health-check coordination. |
| [`health_check/health_check_config.json`](../health_check/health_check_config.json) | Historical identities and environment-based authorized asset locations. |
| [`health_check/health_report.py`](../health_check/health_report.py) | English Markdown rendering of health-check evidence. |
| [`health_check/run_health_check.sh`](../health_check/run_health_check.sh) | Portable Python launcher for the read-only asset checker. |
| [`index.html`](../index.html) | Unmodified existing GitHub Pages entry point to the hosted application. |
| [`scripts/verify_release.py`](../scripts/verify_release.py) | Read-only checker of release-file identities. |
| [`tableau/research_dashboard_template.twb`](../tableau/research_dashboard_template.twb) | Machine-generated Tableau Live Connection template, with credentials removed. |
| [`web/.gitignore`](../web/.gitignore) | Component-specific exclusions for generated and private files. |
| [`web/README.md`](../web/README.md) | Component setup and operational documentation. |
| [`web/app/discover/page.tsx`](../web/app/discover/page.tsx) | Discovery workspace route. |
| [`web/app/discovery/candidate-formulas.ts`](../web/app/discovery/candidate-formulas.ts) | Bounded formulas, lag alignment, AI-structure validation, and candidate evaluation. |
| [`web/app/discovery/evidence-charts.tsx`](../web/app/discovery/evidence-charts.tsx) | Wealth chart and out-of-sample RankIC timeline. |
| [`web/app/discovery/evidence-exports.ts`](../web/app/discovery/evidence-exports.ts) | CSV and Markdown research-evidence downloads. |
| [`web/app/discovery/file-ingestion.ts`](../web/app/discovery/file-ingestion.ts) | Bounded ZIP extraction and single-CSV selection. |
| [`web/app/discovery/portfolio-evidence.ts`](../web/app/discovery/portfolio-evidence.ts) | Frozen ensemble scores, positions, weight drift, turnover, and cost evidence. |
| [`web/app/discovery/statistics.ts`](../web/app/discovery/statistics.ts) | Ranks, correlations, HAC uncertainty, binomial tails, and Holm correction. |
| [`web/app/discovery/worker-types.ts`](../web/app/discovery/worker-types.ts) | Typed worker messages, configuration, panels, candidates, and metrics. |
| [`web/app/discovery/workspace-types.ts`](../web/app/discovery/workspace-types.ts) | UI evidence contracts, frequency options, and workspace states. |
| [`web/app/factor-discovery.worker.ts`](../web/app/factor-discovery.worker.ts) | Worker messages, panel audit, chronological stages, and annual walk-forward orchestration. |
| [`web/app/factor-registry-panel.tsx`](../web/app/factor-registry-panel.tsx) | Read-only development registry and model-status evidence. |
| [`web/app/globals.css`](../web/app/globals.css) | Shared interface styles. |
| [`web/app/layout.tsx`](../web/app/layout.tsx) | Shared page metadata and document layout. |
| [`web/app/page.tsx`](../web/app/page.tsx) | Public overview and stored research-evidence page. |
| [`web/app/platform-data.ts`](../web/app/platform-data.ts) | Historical development snapshot; not a new backtest. |
| [`web/app/sample-data-panel.tsx`](../web/app/sample-data-panel.tsx) | Synthetic downloadable example panel and documentation. |
| [`web/app/site-header.tsx`](../web/app/site-header.tsx) | Shared navigation header. |
| [`web/app/upload-discovery-workspace.tsx`](../web/app/upload-discovery-workspace.tsx) | Interactive upload, mapping, audit, execution, and results workspace. |
| [`web/build/sites-vite-plugin.ts`](../web/build/sites-vite-plugin.ts) | Existing hosting/build integration plugin. |
| [`web/eslint.config.mjs`](../web/eslint.config.mjs) | Component configuration: eslint config. |
| [`web/next-env.d.ts`](../web/next-env.d.ts) | Component configuration: next-env d. |
| [`web/next.config.ts`](../web/next.config.ts) | Component configuration: next config. |
| [`web/package-lock.json`](../web/package-lock.json) | Machine-generated dependency lockfile; not hand-maintained source. |
| [`web/package.json`](../web/package.json) | Component configuration: package. |
| [`web/pnpm-lock.yaml`](../web/pnpm-lock.yaml) | Machine-generated dependency lockfile; not hand-maintained source. |
| [`web/postcss.config.mjs`](../web/postcss.config.mjs) | Component configuration: postcss config. |
| [`web/public/factor-discovery.worker.js`](../web/public/factor-discovery.worker.js) | Generated, self-contained browser worker; rebuild from TypeScript modules. |
| [`web/public/favicon.svg`](../web/public/favicon.svg) | Public platform icon. |
| [`web/public/platform-preview.png`](../web/public/platform-preview.png) | Public platform preview image. |
| [`web/public/research-method.md`](../web/public/research-method.md) | Browser research contract and interpretation limitations. |
| [`web/scripts/build-browser-worker.mjs`](../web/scripts/build-browser-worker.mjs) | Bundle the worker modules into one browser asset. |
| [`web/scripts/dev.mjs`](../web/scripts/dev.mjs) | Portable web launcher; private local API disabled by default. |
| [`web/tests/browser-worker.test.mjs`](../web/tests/browser-worker.test.mjs) | Synthetic production-worker audit and signal/null regression tests. |
| [`web/tests/rendered-html.test.mjs`](../web/tests/rendered-html.test.mjs) | Production-page rendering, evidence disclosure, and UI contract tests. |
| [`web/tsconfig.json`](../web/tsconfig.json) | Component configuration: tsconfig. |
| [`web/vite.config.ts`](../web/vite.config.ts) | Component configuration: vite config. |
| [`web/worker/index.ts`](../web/worker/index.ts) | Server request and image-optimization entry point. |
