import assert from "node:assert/strict";
import { File } from "node:buffer";
import { readFile } from "node:fs/promises";
import test from "node:test";

function panelCsv({ futureAvailability = false, months = 72 } = {}) {
  const lines = ["asset_id,date,available_date,forward_return,value,quality,momentum,volatility"];
  for (let month = 0; month < months; month += 1) {
    const date = new Date(Date.UTC(2020 + Math.floor(month / 12), month % 12, 1)).toISOString().slice(0, 10);
    for (let asset = 1; asset <= 20; asset += 1) {
      const value = ((asset * 7 + month * 3) % 23) / 22;
      const quality = ((asset * 11 + month * 5) % 29) / 28;
      const momentum = Math.sin((asset + month) / 3);
      const volatility = 0.1 + ((asset * 5 + month * 2) % 17) / 40;
      const noise = Math.sin(asset * 13 + month * 7) * 0.006;
      const forwardReturn = 0.035 * value + 0.025 * quality + 0.018 * momentum - 0.025 * volatility + noise;
      const availableDate = futureAvailability && month === 0 && asset === 1 ? "2020-02-01" : date;
      lines.push([`A${String(asset).padStart(2, "0")}`, date, availableDate, forwardReturn.toFixed(6), value.toFixed(6), quality.toFixed(6), momentum.toFixed(6), volatility.toFixed(6)].join(","));
    }
  }
  return `${lines.join("\n")}\n`;
}

function dailyPanelCsv({ tradingDays = 900, assets = 12 } = {}) {
  const rows = [["asset_id", "date", "available_date", "forward_return", "value", "quality", "momentum", "volatility"]];
  let calendarDay = 0;
  for (let tradingDay = 0; tradingDay < tradingDays; tradingDay += 1) {
    let date = new Date(Date.UTC(2018, 0, 1 + calendarDay));
    while (date.getUTCDay() === 0 || date.getUTCDay() === 6) {
      calendarDay += 1;
      date = new Date(Date.UTC(2018, 0, 1 + calendarDay));
    }
    const dateText = date.toISOString().slice(0, 10);
    for (let asset = 1; asset <= assets; asset += 1) {
      const signal = ((asset * 7 + tradingDay * 3) % 31) / 30;
      const noise = Math.sin(asset * 11 + tradingDay * 5) * 0.004;
      rows.push([`A${asset}`, dateText, dateText, (0.025 * signal + noise).toFixed(8), signal.toFixed(8), ((asset + tradingDay) % 17 / 16).toFixed(8), Math.sin((asset + tradingDay) / 4).toFixed(8), (0.1 + asset / 100).toFixed(8)]);
    }
    calendarDay += 1;
  }
  return rows.map((row) => row.join(",")).join("\n");
}

function intervalPanelCsv({ frequency, periods = 30, assets = 6 }) {
  const rows = [["asset_id", "date", "available_date", "forward_return", "value", "quality", "momentum", "volatility"]];
  for (let period = 0; period < periods; period += 1) {
    const date = frequency === "weekly"
      ? new Date(Date.UTC(2020, 0, 6 + period * 7))
      : new Date(Date.UTC(2015 + Math.floor(period * 3 / 12), (period * 3) % 12, 1));
    const dateText = date.toISOString().slice(0, 10);
    for (let asset = 1; asset <= assets; asset += 1) {
      rows.push([`A${asset}`, dateText, dateText, "0.01", `${asset / assets}`, `${period / periods}`, `${(asset + period) % 7}`, `${0.1 + asset / 100}`]);
    }
  }
  return rows.map((row) => row.join(",")).join("\n");
}

function benchmarkPanelCsv({ mode, months = 120, assets = 40, seed = 0x9e3779b9 }) {
  const lines = ["asset_id,date,available_date,forward_return,alpha_signal,noise_a,noise_b,noise_c"];
  let state = seed;
  const random = () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 0x100000000;
  };
  const previousAlpha = new Array(assets + 1).fill(0);
  for (let month = 0; month < months; month += 1) {
    const date = new Date(Date.UTC(2000 + Math.floor(month / 12), month % 12, 1)).toISOString().slice(0, 10);
    for (let asset = 1; asset <= assets; asset += 1) {
      const alphaSignal = random() * 2 - 1;
      const noiseA = random() * 2 - 1;
      const noiseB = random() * 2 - 1;
      const noiseC = random() * 2 - 1;
      const returnNoise = (random() * 2 - 1) * 0.004;
      const signalActive = mode === "stable" || (mode === "decay" && month < 72);
      const signalReturn = signalActive
        ? 0.04 * alphaSignal
        : mode === "lagged" && month > 0
          ? 0.04 * previousAlpha[asset]
          : mode === "interaction"
            ? 0.04 * alphaSignal * noiseA
            : 0;
      const forwardReturn = signalReturn + returnNoise;
      lines.push([
        `A${String(asset).padStart(3, "0")}`,
        date,
        date,
        forwardReturn.toFixed(8),
        alphaSignal.toFixed(8),
        noiseA.toFixed(8),
        noiseB.toFixed(8),
        noiseC.toFixed(8),
      ].join(","));
      previousAlpha[asset] = alphaSignal;
    }
  }
  return `${lines.join("\n")}\n`;
}

async function workerHarness() {
  const source = await readFile(new URL("../public/factor-discovery.worker.js", import.meta.url), "utf8");
  const messages = [];
  globalThis.self = { postMessage: (message) => messages.push(message) };
  new Function(source)();
  const workerSelf = globalThis.self;
  return {
    messages,
    async dispatch(data, terminalTypes) {
      const start = messages.length;
      workerSelf.onmessage({ data });
      const deadline = Date.now() + 10_000;
      while (Date.now() < deadline) {
        const terminal = messages.slice(start).find((message) => terminalTypes.includes(message.type));
        if (terminal) return terminal;
        await new Promise((resolve) => setTimeout(resolve, 5));
      }
      throw new Error(`Worker timed out waiting for ${terminalTypes.join(" or ")}`);
    },
  };
}

const config = {
  entityColumn: "asset_id",
  dateColumn: "date",
  targetColumn: "forward_return",
  availabilityColumn: "available_date",
  frequency: "monthly",
  targetHorizonPeriods: 1,
  featureColumns: ["value", "quality", "momentum", "volatility"],
  candidateBudget: 100,
  correlationThreshold: 0.8,
  transactionCostBps: 25,
};

const benchmarkConfig = {
  ...config,
  featureColumns: ["alpha_signal", "noise_a", "noise_b", "noise_c"],
  transactionCostBps: 10,
};

test("requires a passing audit before discovery and completes after audit", async () => {
  const harness = await workerHarness();
  const file = new File([panelCsv()], "panel.csv", { type: "text/csv" });
  const inspection = await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"]);
  assert.equal(inspection.type, "INSPECTION");

  const locked = await harness.dispatch({ type: "RUN", config }, ["RESULT", "ERROR"]);
  assert.equal(locked.type, "ERROR");
  assert.match(locked.message, /Audit the current data mapping/);

  const audit = await harness.dispatch({ type: "AUDIT", config }, ["AUDIT_RESULT", "ERROR"]);
  assert.equal(audit.type, "AUDIT_RESULT");
  assert.equal(audit.result.passed, true);
  assert.equal(audit.result.summary.duplicateKeys, 0);
  assert.equal(audit.result.summary.futureAvailabilityRows, 0);

  const result = await harness.dispatch({ type: "RUN", config }, ["RESULT", "ERROR"]);
  assert.equal(result.type, "RESULT");
  assert.equal(result.result.schemaVersion, "browser-factor-discovery.v10");
  assert.equal(result.result.source.dataLeftBrowser, false);
  assert.equal(result.result.validation.purge.totalPurgedPeriods, 2);
  assert.equal(result.result.validation.multipleTesting.method, "Holm-Bonferroni joint family");
  assert.equal(result.result.validation.portfolio.transactionCostBps, 25);
  assert.equal(result.result.validation.walkForward.protocol, "frequency-aware-monthly-full-year-refit");
  assert.equal(result.result.validation.walkForward.eligiblePeriods, 39);
  assert.equal(result.result.validation.walkForward.excludedLeadingPartialPeriods, 3);
  assert.equal(result.result.validation.walkForward.eligibleBlocks, 3);
  assert.equal(result.result.validation.walkForward.evaluatedBlocks, 3);
  assert.equal(result.result.validation.walkForward.evaluatedPeriods, 36);
  assert.equal(result.result.validation.walkForward.truncated, false);
  assert.equal(result.result.validation.walkForward.blocks.length, 3);
  assert.equal(result.result.validation.walkForward.periods.length, 36);
  assert.equal(result.result.validation.walkForward.deployedBlocks + result.result.validation.walkForward.cashBlocks, 3);
  assert.ok(Number.isFinite(result.result.validation.walkForward.net.mean));
  assert.equal(result.result.validation.gates.length, 7);
  assert.equal(result.result.validation.gates.every((gate) => typeof gate.detail === "string" && gate.detail.length > 0), true);
  assert.equal(result.result.validation.gates.every((gate) => gate.passed), true);
  assert.equal(result.result.validation.passed, true);
  assert.ok(Number.isFinite(result.result.validation.portfolio.net.mean));
  assert.ok(result.result.validation.portfolio.net.mean > 0);
});

test("evaluates every complete annual block when the adaptive budget permits", async () => {
  const harness = await workerHarness();
  const file = new File([panelCsv({ months: 84 })], "long-panel.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const result = await harness.dispatch({ type: "RUN", config }, ["RESULT", "ERROR"]);
  assert.equal(result.type, "RESULT");
  assert.equal(result.result.validation.walkForward.eligiblePeriods, 51);
  assert.equal(result.result.validation.walkForward.excludedLeadingPartialPeriods, 3);
  assert.equal(result.result.validation.walkForward.eligibleBlocks, 4);
  assert.equal(result.result.validation.walkForward.evaluatedBlocks, 4);
  assert.equal(result.result.validation.walkForward.evaluatedPeriods, 48);
  assert.equal(result.result.validation.walkForward.truncated, false);
  assert.ok(result.result.resourceUse.estimatedRollingCandidateObservations > 0);
  assert.equal(
    result.result.resourceUse.totalEstimatedCandidateObservations,
    result.result.resourceUse.candidateObservations + result.result.resourceUse.estimatedRollingCandidateObservations,
  );
});

test("blocks rows whose feature availability occurs after observation", async () => {
  const harness = await workerHarness();
  const file = new File([panelCsv({ futureAvailability: true })], "future.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  const audit = await harness.dispatch({ type: "AUDIT", config }, ["AUDIT_RESULT", "ERROR"]);
  assert.equal(audit.type, "AUDIT_RESULT");
  assert.equal(audit.result.passed, false);
  assert.equal(audit.result.summary.futureAvailabilityRows, 1);
  assert.equal(audit.result.checks.find((check) => check.id === "availability")?.status, "FAIL");
});

test("requires enough history for the declared return horizon and purge", async () => {
  const harness = await workerHarness();
  const file = new File([panelCsv({ months: 36 })], "short-for-horizon.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  const audit = await harness.dispatch({ type: "AUDIT", config: { ...config, targetHorizonPeriods: 12 } }, ["AUDIT_RESULT", "ERROR"]);
  assert.equal(audit.type, "AUDIT_RESULT");
  assert.equal(audit.result.passed, false);
  assert.equal(audit.result.checks.find((check) => check.id === "period-coverage")?.status, "FAIL");
});

test("auto-detects and runs a daily panel with frequency-aware windows", async () => {
  const harness = await workerHarness();
  const file = new File([dailyPanelCsv()], "daily-panel.csv", { type: "text/csv" });
  const inspection = await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"]);
  assert.equal(inspection.type, "INSPECTION");
  assert.equal(inspection.inspection.suggested.frequency, "daily");
  const dailyConfig = { ...config, frequency: "daily", targetHorizonPeriods: 1, candidateBudget: 100 };
  const audit = await harness.dispatch({ type: "AUDIT", config: dailyConfig }, ["AUDIT_RESULT", "ERROR"]);
  assert.equal(audit.result.passed, true);
  const result = await harness.dispatch({ type: "RUN", config: dailyConfig }, ["RESULT", "ERROR"]);
  assert.equal(result.type, "RESULT");
  assert.equal(result.result.validation.walkForward.frequency, "daily");
  assert.equal(result.result.validation.walkForward.periodsPerYear, 252);
  assert.equal(result.result.validation.walkForward.testBlockPeriods, 252);
});

test("auto-detects weekly and quarterly panels", async () => {
  for (const frequency of ["weekly", "quarterly"]) {
    const harness = await workerHarness();
    const file = new File([intervalPanelCsv({ frequency })], `${frequency}-panel.csv`, { type: "text/csv" });
    const inspection = await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"]);
    assert.equal(inspection.type, "INSPECTION");
    assert.equal(inspection.inspection.suggested.frequency, frequency);
  }
});

test("benchmark: recovers a persistent planted signal with the production worker", async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "stable" })], "benchmark-stable.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const message = await harness.dispatch({ type: "RUN", config: benchmarkConfig }, ["RESULT", "ERROR"]);
  assert.equal(message.type, "RESULT");
  assert.equal(message.result.validation.passed, true);
  assert.equal(message.result.assessment.tier, "validated");
  assert.ok(message.result.components.some((component) => component.expression.includes("alpha_signal")));
  assert.ok(message.result.validation.walkForward.oosRankIC.mean > 0.25);
  assert.ok(message.result.validation.walkForward.net.mean > 0);
});

test("benchmark: does not validate an all-noise panel", async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "null" })], "benchmark-null.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const message = await harness.dispatch({ type: "RUN", config: benchmarkConfig }, ["RESULT", "ERROR"]);
  assert.equal(message.type, "RESULT");
  assert.equal(message.result.validation.passed, false);
  assert.notEqual(message.result.assessment.tier, "validated");
  assert.ok(message.result.validation.gates.some((gate) => !gate.passed));
});

test("benchmark: rejects a signal that disappears before validation", async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "decay" })], "benchmark-decay.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const message = await harness.dispatch({ type: "RUN", config: benchmarkConfig }, ["RESULT", "ERROR"]);
  assert.equal(message.type, "RESULT");
  assert.equal(message.result.validation.passed, false);
  assert.notEqual(message.result.assessment.tier, "validated");
  assert.equal(message.result.validation.gates.find((gate) => gate.id === "calibration-signal")?.passed, false);
});

test("benchmark: recovers a signal available only through same-asset lag history", async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "lagged" })], "benchmark-lagged.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const message = await harness.dispatch({ type: "RUN", config: benchmarkConfig }, ["RESULT", "ERROR"]);
  assert.equal(message.type, "RESULT");
  assert.ok(message.result.components.some((component) => component.expression === "lag_1(alpha_signal)"));
  assert.ok(message.result.validation.walkForward.oosRankIC.mean > 0.25);
});

test("benchmark: recovers a nonlinear interaction instead of either primitive alone", async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "interaction" })], "benchmark-interaction.csv", { type: "text/csv" });
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const message = await harness.dispatch({ type: "RUN", config: benchmarkConfig }, ["RESULT", "ERROR"]);
  assert.equal(message.type, "RESULT");
  assert.ok(message.result.components.some((component) => component.operation === "product" && component.expression.includes("alpha_signal") && component.expression.includes("noise_a")));
  assert.ok(message.result.validation.walkForward.oosRankIC.mean > 0.2);
});

test("benchmark: controls false validation across multiple independent null panels", async () => {
  for (const seed of [11, 29, 47, 71, 101]) {
    const harness = await workerHarness();
    const file = new File([benchmarkPanelCsv({ mode: "null", seed })], `benchmark-null-${seed}.csv`, { type: "text/csv" });
    assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
    assert.equal((await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
    const message = await harness.dispatch({ type: "RUN", config: benchmarkConfig }, ["RESULT", "ERROR"]);
    assert.equal(message.type, "RESULT");
    assert.equal(message.result.validation.passed, false, `null seed ${seed} was falsely validated`);
  }
});

test("benchmark: persistent signal recovery is repeatable across independent panels", async () => {
  for (const seed of [13, 43, 89]) {
    const harness = await workerHarness();
    const file = new File([benchmarkPanelCsv({ mode: "stable", seed })], `benchmark-stable-${seed}.csv`, { type: "text/csv" });
    assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
    assert.equal((await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
    const message = await harness.dispatch({ type: "RUN", config: benchmarkConfig }, ["RESULT", "ERROR"]);
    assert.equal(message.type, "RESULT");
    assert.equal(message.result.validation.passed, true, `stable seed ${seed} was not validated`);
    assert.ok(message.result.components.some((component) => component.expression.includes("alpha_signal")));
  }
});

test("AI proposals are marked, bounded, and still evaluated by the production engine", async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "lagged" })], "benchmark-ai-proposal.csv", { type: "text/csv" });
  const aiConfig = {
    ...benchmarkConfig,
    aiProposals: [
      {
        operation: "lag1",
        left_feature: "alpha_signal",
        right_feature: null,
        rationale_key: "PERSISTENCE",
        decision_authority: false,
      },
    ],
  };
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config: aiConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const message = await harness.dispatch({ type: "RUN", config: aiConfig }, ["RESULT", "ERROR"]);
  assert.equal(message.type, "RESULT");
  const proposed = message.result.components.find((component) => component.expression === "lag_1(alpha_signal)");
  assert.equal(proposed?.source, "ai-proposed");
  assert.ok(proposed.selection.validPeriods > 0);
  assert.ok(message.result.validation.walkForward.oosRankIC.mean > 0.25);
});

test("rejects an AI proposal that references an unmapped feature", async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "stable" })], "benchmark-invalid-ai.csv", { type: "text/csv" });
  const invalidConfig = {
    ...benchmarkConfig,
    aiProposals: [
      {
        operation: "identity",
        left_feature: "unknown_feature",
        right_feature: null,
        rationale_key: "LEVEL_EFFECT",
        decision_authority: false,
      },
    ],
  };
  assert.equal((await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"])).type, "INSPECTION");
  assert.equal((await harness.dispatch({ type: "AUDIT", config: invalidConfig }, ["AUDIT_RESULT", "ERROR"])).result.passed, true);
  const message = await harness.dispatch({ type: "RUN", config: invalidConfig }, ["RESULT", "ERROR"]);
  assert.equal(message.type, "ERROR");
  assert.match(message.message, /deterministic validation/);
});

test("streams a high-row-count panel within the declared browser budget", { timeout: 30_000 }, async () => {
  const harness = await workerHarness();
  const file = new File([benchmarkPanelCsv({ mode: "stable", months: 120, assets: 1_000, seed: 131 })], "benchmark-120k.csv", { type: "text/csv" });
  const inspection = await harness.dispatch({ type: "INSPECT", file }, ["INSPECTION", "ERROR"]);
  assert.equal(inspection.type, "INSPECTION");
  assert.equal(inspection.inspection.rowCount, 120_000);
  const audit = await harness.dispatch({ type: "AUDIT", config: benchmarkConfig }, ["AUDIT_RESULT", "ERROR"]);
  assert.equal(audit.type, "AUDIT_RESULT");
  assert.equal(audit.result.passed, true);
});

test("rejects a CSV above the published 200 MB limit before parsing", async () => {
  const harness = await workerHarness();
  const oversized = new File([new Blob([], { endings: "transparent" })], "oversized.csv", { type: "text/csv" });
  Object.defineProperty(oversized, "size", { value: 200 * 1024 * 1024 + 1 });
  const message = await harness.dispatch({ type: "INSPECT", file: oversized }, ["INSPECTION", "ERROR"]);
  assert.equal(message.type, "ERROR");
  assert.match(message.message, /up to 200\.0 MB/);
});
