import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("separates the public overview, example data, and real registry evidence", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = (await response.text()).replaceAll("<!-- -->", "");
  assert.match(html, /<html lang="en"/i);
  assert.match(html, /<title>Factor Discovery — Automatic Factor Research<\/title>/i);
  assert.match(html, /Discover factors\..*Audit every step\./s);
  assert.match(html, /href="\/discover"/);
  assert.match(html, /See the format before using the platform\./);
  assert.match(html, /Download example CSV/);
  assert.match(html, /This synthetic panel is documentation only/);
  assert.match(html, /A real development result—not a final model\./);
  assert.match(html, /Cost-aware gate/);
  assert.match(html, /No final model|Final model created/s);
  assert.match(html, /CRSP monthly returns/);
  assert.match(html, /Compustat Point-in-Time fundamentals/);
  assert.match(html, /1990-01-31 — 2016-11-30/);
  assert.match(html, /527,211 derived factor rows/);
  assert.match(html, /These are real outputs copied from the stored research artifacts/);
  assert.match(html, /Download the browser worker/);
  assert.match(html, /Download the research contract/);
  assert.match(html, /0\.6765/);
  assert.match(html, /platform-preview\.png/);
  assert.doesNotMatch(html, /V8|RESEARCH RELEASE|12 AUG 2026|wordmark-symbol|local edition/i);
  assert.doesNotMatch(html, /type="file"/);
});

test("renders the separate discovery workspace with all usable features visible", async () => {
  const response = await render("/discover");
  assert.equal(response.status, 200);
  const html = (await response.text()).replaceAll("<!-- -->", "");
  assert.match(html, /Bring a panel\. Discover factors\./);
  assert.match(html, /ON-DEVICE PRIVACY/);
  assert.match(html, /Your file stays on your device\./);
  assert.match(html, /CSV or one-CSV ZIP · 200 MB · 500k rows/);
  assert.match(html, /2–50 numeric features/);
  assert.match(html, /640 MB memory guard/);
  assert.match(html, /type="file"/);
  assert.match(html, /Audit data/);
  assert.match(html, /Run discovery/);
  assert.doesNotMatch(html, /Sample CSV|V8|local edition/i);
  const browserWorker = await readFile(new URL("../public/factor-discovery.worker.js", import.meta.url), "utf8");
  const workspaceSource = (await Promise.all([
    "../app/upload-discovery-workspace.tsx", "../app/discovery/workspace-types.ts",
    "../app/discovery/evidence-charts.tsx", "../app/discovery/evidence-exports.ts",
  ].map((path) => readFile(new URL(path, import.meta.url), "utf8")))).join("\n");
  assert.match(workspaceSource, /Point-in-time availability/);
  assert.match(workspaceSource, /Target horizon/);
  assert.match(workspaceSource, /Transaction cost/);
  assert.match(workspaceSource, /Purged, multiplicity-adjusted, and cost-aware/);
  assert.match(workspaceSource, /FREQUENCY-AWARE WALK-FORWARD/);
  assert.match(workspaceSource, /Daily.*Weekly.*Monthly.*Quarterly/s);
  assert.match(workspaceSource, /testBlockPeriods/);
  assert.match(workspaceSource, /REPRODUCIBILITY EXPORTS/);
  assert.match(workspaceSource, /Factor definition CSV/);
  assert.match(workspaceSource, /Walk-forward CSV/);
  assert.match(workspaceSource, /PERFORMANCE TRACE/);
  assert.match(workspaceSource, /DECISION LEDGER/);
  assert.match(workspaceSource, /FULL-YEAR BLOCK LEDGER/);
  assert.match(workspaceSource, /DISCOVERED FORMULA/);
  assert.match(workspaceSource, /EVIDENCE, NOT A BINARY SEARCH RESULT/);
  assert.match(workspaceSource, /factorDefinitionCsv/);
  assert.match(workspaceSource, /walkForwardCsv/);
  assert.match(workspaceSource, /validationReport/);
  assert.match(workspaceSource, /one full year of/);
  assert.match(workspaceSource, /Audit dataset/);
  assert.match(workspaceSource, /Complete data audit to unlock discovery/);
  assert.match(workspaceSource, /OPTIONAL IN-BROWSER AI/);
  assert.match(workspaceSource, /Use browser AI/);
  assert.match(workspaceSource, /no account or API key/);
  assert.match(workspaceSource, /availableFeatureColumns\.map/);
  assert.match(workspaceSource, /selected · \{availableFeatureColumns\.length\} available · maximum 50/);
  assert.doesNotMatch(workspaceSource, /\/50 selected|downloadSampleCsv/);
  assert.match(workspaceSource, /Why transformations did not advance/);
  assert.match(workspaceSource, /Why this matters/);
  assert.match(browserWorker, /ctx\.onmessage/);
  assert.match(browserWorker, /file\.stream\(\)/);
  assert.match(browserWorker, /AUDIT_RESULT/);
  assert.match(browserWorker, /Audit the current data mapping before running discovery/);
  assert.match(browserWorker, /Holm-Bonferroni joint family/);
  assert.match(browserWorker, /equal-weight top-minus-bottom 20%/);
  assert.match(browserWorker, /frequency-aware-\$\{config\.frequency\}-full-year-refit/);
  assert.match(browserWorker, /rolling_mean_3/);
  assert.match(browserWorker, /rolling_volatility_3/);
  assert.match(browserWorker, /source: "ai-proposed"/);
  assert.match(browserWorker, /An AI proposal failed deterministic validation/);
  assert.match(browserWorker, /MAX_WALK_FORWARD_CANDIDATE_OBSERVATIONS/);
  assert.doesNotMatch(browserWorker, /file\.text\(\)/);
  assert.doesNotMatch(browserWorker, /factor-discovery\.worker\.ts\?/);
  assert.doesNotMatch(html, /\p{Script=Han}|kill switch|qwen3/iu);
  assert.doesNotMatch(html, /Your site is taking shape|react-loading-skeleton/);
  assert.doesNotMatch(html, /<form|api\/candidates/i);
});
