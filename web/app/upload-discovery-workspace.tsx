"use client";
import { downloadText, factorDefinitionCsv, walkForwardCsv, validationReport } from "./discovery/evidence-exports";
import { WalkForwardWealthChart, RankICTimeline } from "./discovery/evidence-charts";
import { extractCsv, MAX_UNCOMPRESSED_CSV_BYTES } from "./discovery/file-ingestion";
import { Inspection, DataFrequency, FREQUENCY_OPTIONS, AuditResult, DiscoveryResult, WorkerMessage, Phase, AIProposal } from "./discovery/workspace-types";

import { useEffect, useRef, useState } from "react";
const BROWSER_AI_MODEL = "Qwen3-0.6B-q4f16_1-MLC";
const AI_OPERATIONS = new Set<AIProposal["operation"]>(["identity", "square", "lag1", "change1", "growth1", "mean3", "volatility3", "difference", "product", "ratio"]);
const BINARY_AI_OPERATIONS = new Set<AIProposal["operation"]>(["difference", "product", "ratio"]);

function compactColumn(value: string) {
  return value.replaceAll("_", " ");
}

function gateInterpretation(id: string) {
  const explanations: Record<string, string> = {
    "calibration-signal": "Failure means the factor's ranking relationship was too small or too inconsistent in the separate Calibration sample. It may be noise, unstable, or dependent on a few periods.",
    multiplicity: "Failure means the apparent signal was no longer unusual after accounting for the number of candidates tested. This protects against finding a lucky formula by searching widely.",
    "calibration-net-return": "Failure means the long-short spread was not positive after the selected trading-cost assumption. Statistical association alone may not be economically implementable.",
    "calibration-net-inference": "Failure means the cost-adjusted return estimate was too imprecise to distinguish from zero at the configured evidence level.",
    "walk-forward-coverage": "Failure means the history did not contain three complete untouched full-year test blocks at the selected frequency. Candidates can still be reported, but the platform cannot call them fully validated.",
    "walk-forward-deployment": "Failure means no full-year model cleared its pre-trade Calibration gate, so the disciplined strategy would have stayed in cash.",
    "walk-forward-net-return": "Failure means the sequence of frozen full-year decisions did not produce a positive mean net spread, including cash periods and turnover costs.",
  };
  return explanations[id] ?? "This configured validation requirement was not met.";
}

function formatFileSize(bytes: number) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function generatedCandidateCount(featureCount: number, budget: number) {
  return Math.min(budget, featureCount + 3 * featureCount * (featureCount - 1) / 2);
}

function workloadFits(rowCount: number, featureCount: number, budget: number) {
  return rowCount * generatedCandidateCount(featureCount, budget) <= 75_000_000;
}

export function UploadDiscoveryWorkspace() {
  const workerRef = useRef<Worker | null>(null);
  const aiEngineRef = useRef<unknown>(null);
  const [phase, setPhase] = useState<Phase>("empty");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [entityColumn, setEntityColumn] = useState("");
  const [dateColumn, setDateColumn] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [availabilityColumn, setAvailabilityColumn] = useState("");
  const [frequency, setFrequency] = useState<DataFrequency>("monthly");
  const [targetHorizonPeriods, setTargetHorizonPeriods] = useState(1);
  const [featureColumns, setFeatureColumns] = useState<string[]>([]);
  const [candidateBudget, setCandidateBudget] = useState(250);
  const [correlationThreshold, setCorrelationThreshold] = useState(0.8);
  const [transactionCostBps, setTransactionCostBps] = useState(25);
  const [aiProposals, setAiProposals] = useState<AIProposal[]>([]);
  const [aiProposalState, setAiProposalState] = useState<"checking" | "ready" | "unavailable" | "running" | "complete" | "error">("checking");
  const [aiProposalMessage, setAiProposalMessage] = useState("Checking whether this browser can run the embedded open model…");
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("Choose a CSV panel to begin.");
  const [error, setError] = useState("");
  const [audit, setAudit] = useState<AuditResult | null>(null);
  const [result, setResult] = useState<DiscoveryResult | null>(null);

  useEffect(() => {
    let worker: Worker;
    try {
      worker = new Worker("/factor-discovery.worker.js", { type: "module", name: "factor-discovery" });
    } catch {
      const failureTimer = window.setTimeout(() => {
        setError("The private discovery engine could not start in this browser.");
        setPhase("error");
      }, 0);
      return () => window.clearTimeout(failureTimer);
    }
    workerRef.current = worker;
    worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
      const message = event.data;
      if (message.type === "INSPECTION") {
        setInspection(message.inspection);
        setEntityColumn(message.inspection.suggested.entityColumn);
        setDateColumn(message.inspection.suggested.dateColumn);
        setTargetColumn(message.inspection.suggested.targetColumn);
        setAvailabilityColumn(message.inspection.suggested.availabilityColumn);
        setFrequency(message.inspection.suggested.frequency);
        setTargetHorizonPeriods(1);
        setFeatureColumns(message.inspection.suggested.featureColumns);
        setCandidateBudget(workloadFits(message.inspection.rowCount, message.inspection.suggested.featureColumns.length, 250) ? 250 : 100);
        setAudit(null);
        setPhase("mapping");
        setProgress(0);
        setStage("Map the panel columns and choose the candidate budget.");
      } else if (message.type === "AUDIT_RESULT") {
        setAudit(message.result);
        setPhase("audited");
        setProgress(100);
        setStage(message.result.passed ? "Data audit passed. Discovery is unlocked." : "Data audit found blocking issues.");
      } else if (message.type === "PROGRESS") {
        setProgress(message.progress);
        setStage(message.stage);
      } else if (message.type === "RESULT") {
        setResult(message.result);
        setPhase("complete");
        setProgress(100);
        setStage("Private discovery complete. The result remains in this browser session.");
      } else {
        setError(message.message);
        setPhase("error");
        setStage("Discovery stopped before producing a result.");
      }
    };
    worker.onerror = () => {
      setError("The private discovery engine stopped unexpectedly.");
      setPhase("error");
      setStage("Discovery stopped before producing a result.");
    };
    return () => worker.terminate();
  }, []);

  useEffect(() => {
    if (!(navigator as Navigator & { gpu?: unknown }).gpu) {
      setAiProposalState("unavailable");
      setAiProposalMessage("This browser does not expose WebGPU. Deterministic automatic discovery remains fully available.");
      return;
    }
    setAiProposalState("ready");
    setAiProposalMessage("Ready. First use downloads and caches an open model in this browser; no API key or local setup is required.");
  }, []);

  async function inspectFile(file: File | undefined) {
    if (!file) return;
    setError("");
    setAudit(null);
    setResult(null);
    setInspection(null);
    setFeatureColumns([]);
    setAiProposals([]);
    if (!/\.(csv|zip)$/i.test(file.name)) {
      setError("Choose a CSV file or a ZIP containing exactly one CSV file.");
      setPhase("error");
      return;
    }
    if (file.size > MAX_UNCOMPRESSED_CSV_BYTES) {
      setError("The browser workspace accepts files up to 200 MB.");
      setPhase("error");
      return;
    }
    setPhase("inspecting");
    setProgress(1);
    setStage(file.name.toLowerCase().endsWith(".zip") ? "Extracting one CSV from the ZIP locally…" : "Scanning the CSV locally in chunks…");
    try {
      const csvFile = await extractCsv(file);
      workerRef.current?.postMessage({ type: "INSPECT", file: csvFile });
    } catch (inspectionError) {
      setError(inspectionError instanceof Error ? inspectionError.message : "The browser could not read this file.");
      setPhase("error");
    }
  }

  function invalidateAudit() {
    setAudit(null);
    setResult(null);
    setError("");
    setAiProposals([]);
    if (inspection) {
      setPhase("mapping");
      setProgress(0);
      setStage("Data mapping changed. Run the data audit again.");
    }
  }

  function toggleFeature(column: string) {
    const next = featureColumns.includes(column)
      ? featureColumns.filter((item) => item !== column)
      : featureColumns.length < 50 ? [...featureColumns, column] : featureColumns;
    setFeatureColumns(next);
    invalidateAudit();
    if (inspection && !workloadFits(inspection.rowCount, next.length, candidateBudget)) setCandidateBudget(100);
  }

  function researchConfig() {
    return {
      entityColumn,
      dateColumn,
      targetColumn,
      availabilityColumn,
      frequency,
      targetHorizonPeriods,
      featureColumns,
      candidateBudget,
      correlationThreshold,
      transactionCostBps,
      aiProposals,
    };
  }

  async function requestAIProposals() {
    if (aiProposalState !== "ready" && aiProposalState !== "complete") return;
    setAiProposalState("running");
    setAiProposalMessage("Loading the open model in this browser…");
    try {
      const webllm = await import("@mlc-ai/web-llm");
      if (!aiEngineRef.current) {
        aiEngineRef.current = await webllm.CreateMLCEngine(BROWSER_AI_MODEL, {
          initProgressCallback: (report) => setAiProposalMessage(report.text || "Downloading the open model…"),
        });
      }
      setAiProposalMessage("The browser model is proposing bounded candidate structures…");
      const engine = aiEngineRef.current as Awaited<ReturnType<typeof webllm.CreateMLCEngine>>;
      const completion = await engine.chat.completions.create({
        messages: [
          { role: "system", content: "Return JSON only. Propose factor transformations, never conclusions. Use only supplied feature names and allowed operations. Unary operations require right_feature=null; binary operations require two different features. decision_authority must be false." },
          { role: "user", content: JSON.stringify({ feature_columns: featureColumns, allowed_operations: Array.from(AI_OPERATIONS), maximum_proposals: 12, required_shape: { proposals: [{ operation: "identity", left_feature: "exact supplied name", right_feature: null, rationale_key: "short label", decision_authority: false }] } }) },
        ],
        temperature: 0.1,
        max_tokens: 700,
        response_format: { type: "json_object" },
        extra_body: { enable_thinking: false },
      });
      const parsed = JSON.parse(completion.choices[0]?.message?.content ?? "{}") as { proposals?: AIProposal[] };
      const proposals = (parsed.proposals ?? []).slice(0, 12).filter((proposal) => {
        if (!AI_OPERATIONS.has(proposal.operation) || !featureColumns.includes(proposal.left_feature) || proposal.decision_authority !== false) return false;
        return BINARY_AI_OPERATIONS.has(proposal.operation)
          ? typeof proposal.right_feature === "string" && featureColumns.includes(proposal.right_feature) && proposal.right_feature !== proposal.left_feature
          : proposal.right_feature === null;
      });
      if (!proposals.length) throw new Error("The browser model returned no valid bounded proposals. Try again or continue with deterministic discovery.");
      setAiProposals(proposals);
      setAiProposalState("complete");
      setAiProposalMessage(`${proposals.length} bounded structures added to the candidate budget. They receive no validation privilege.`);
      setAudit(null);
      setResult(null);
      setPhase("mapping");
    } catch (requestError) {
      setAiProposalState("error");
      setAiProposalMessage(requestError instanceof Error ? requestError.message : "In-browser AI proposal failed.");
    }
  }

  function runAudit() {
    if (!inspection) return;
    if (!entityColumn || !dateColumn || !targetColumn) {
      setError("Map the entity, date, and forward-return columns.");
      setPhase("error");
      return;
    }
    if (featureColumns.length < 2) {
      setError("Select at least two numeric feature columns.");
      setPhase("error");
      return;
    }
    setError("");
    setAudit(null);
    setResult(null);
    setPhase("auditing");
    setProgress(2);
    setStage("Auditing panel integrity and point-in-time validity…");
    workerRef.current?.postMessage({ type: "AUDIT", config: researchConfig() });
  }

  function runDiscovery() {
    if (!inspection) return;
    if (!audit?.passed) {
      setError("Complete a passing data audit before running discovery.");
      setPhase("error");
      return;
    }
    setError("");
    setResult(null);
    setPhase("running");
    setProgress(2);
    setStage("Starting the private browser job…");
    workerRef.current?.postMessage({
      type: "RUN",
      config: researchConfig(),
    });
  }

  function downloadResult() {
    if (!result) return;
    downloadText(`factor-discovery-${result.generatedAt.slice(0, 10)}.json`, `${JSON.stringify(result, null, 2)}\n`, "application/json");
  }

  function downloadFactorDefinitions() {
    if (!result) return;
    downloadText(`factor-definition-${result.generatedAt.slice(0, 10)}.csv`, factorDefinitionCsv(result), "text/csv");
  }

  function downloadWalkForwardEvidence() {
    if (!result) return;
    downloadText(`walk-forward-evidence-${result.generatedAt.slice(0, 10)}.csv`, walkForwardCsv(result), "text/csv");
  }

  function downloadValidationReport() {
    if (!result) return;
    downloadText(`validation-report-${result.generatedAt.slice(0, 10)}.md`, validationReport(result), "text/markdown");
  }

  const canAudit = Boolean(
    inspection
    && entityColumn
    && dateColumn
    && targetColumn
    && featureColumns.length >= 2
    && workloadFits(inspection.rowCount, featureColumns.length, candidateBudget)
    && !["auditing", "running"].includes(phase),
  );
  const canRun = Boolean(
    canAudit
    && audit?.passed,
  );
  const availableFeatureColumns = inspection?.numericColumns.filter(
    (column) => ![entityColumn, dateColumn, targetColumn, availabilityColumn].includes(column),
  ) ?? [];

  return (
    <section className="upload-workspace section" id="discover">
      <div className="section-intro">
        <div><span className="section-index">DISCOVERY WORKSPACE</span><h2>Bring a panel. Discover factors.</h2></div>
        <p>Upload a daily, weekly, monthly, or quarterly asset panel and run the discovery engine entirely in your browser. Your observations are never sent to this site or added to the public registry.</p>
      </div>

      <div className="privacy-banner">
        <span>ON-DEVICE PRIVACY</span>
        <strong>Your file stays on your device.</strong>
        <p>Chunked parsing keeps only mapped columns in memory. No account, server upload, or persistent storage is used.</p>
      </div>

      <div className="upload-shell">
        <aside className="upload-steps" aria-label="Discovery steps">
          {[
            ["01", "Select data", phase !== "empty"],
            ["02", "Map columns", ["mapping", "auditing", "audited", "running", "complete"].includes(phase)],
            ["03", "Audit data", ["auditing", "audited", "running", "complete"].includes(phase)],
            ["04", "Run discovery", ["running", "complete"].includes(phase)],
            ["05", "Review results", phase === "complete"],
          ].map(([number, label, active]) => (
            <div className={active ? "active" : ""} key={String(number)}><span>{number}</span><p>{label}</p></div>
          ))}
          <div className="browser-limits"><b>Browser workspace</b><span>CSV or one-CSV ZIP · 200 MB · 500k rows</span><span>2–50 numeric features</span><span>Short panels allowed; evidence strength adapts</span><span>Annual validation when history permits</span><span>640 MB memory guard</span></div>
        </aside>

        <div className="upload-main">
          <div className="file-drop">
            <div><span className="file-mark">DATA</span><div><strong>{inspection?.filename ?? "Choose an asset panel"}</strong><p>{inspection ? `${inspection.rowCount.toLocaleString()} rows · ${inspection.columns.length} columns · ${formatFileSize(inspection.fileSizeBytes)}` : "Daily, weekly, monthly, or quarterly CSV—or a ZIP containing exactly one CSV."}</p></div></div>
            <div className="file-actions"><label htmlFor="panel-file">{inspection ? "Replace file" : "Choose file"}<input id="panel-file" type="file" accept=".csv,.zip,text/csv,application/zip" onChange={(event) => void inspectFile(event.target.files?.[0])} /></label></div>
          </div>

          <div className="threshold-explainer">
            <div><strong>Frequency-aware spacing</strong><p>The engine detects Daily, Weekly, Monthly, or Quarterly spacing. Market holidays and ordinary weekend gaps are allowed; unusual gaps are warnings, not blockers.</p></div>
            <div><strong>Assets per period</strong><p>Five complete assets is the computational floor for ranks and two portfolio tails. Small cross-sections remain exploratory; broader panels produce more credible inference.</p></div>
            <div><strong>Frequency-aware history</strong><p>Prediction, purge, HAC, research splits, and full-year walk-forward windows all scale to the selected frequency. Short histories can discover candidates but receive a lower evidence tier.</p></div>
          </div>

          {(phase === "inspecting" || phase === "auditing" || phase === "running") && (
            <div className="private-progress" aria-live="polite"><div><span>{stage}</span><b>{progress}%</b></div><div><i style={{ width: `${progress}%` }} /></div></div>
          )}

          {inspection && phase !== "inspecting" && (
            <div className="mapping-panel">
              <div className="mapping-heading"><div><span>DATA CONTRACT</span><h3>Map the research panel</h3></div><p>The target must be a future return that was not available at signal formation time.</p></div>
              <div className="mapping-grid">
                <label>Entity identifier<select value={entityColumn} onChange={(event) => { invalidateAudit(); setEntityColumn(event.target.value); setFeatureColumns((current) => current.filter((column) => column !== event.target.value)); }}>{inspection.columns.map((column) => <option key={column}>{column}</option>)}</select><small>e.g. PERMNO, ticker, asset_id</small></label>
                <label>Observation date<select value={dateColumn} onChange={(event) => { invalidateAudit(); setDateColumn(event.target.value); setFeatureColumns((current) => current.filter((column) => column !== event.target.value)); }}>{inspection.dateColumns.map((column) => <option key={column}>{column}</option>)}</select><small>Signal formation date</small></label>
                <label>Forward return target<select value={targetColumn} onChange={(event) => { invalidateAudit(); setTargetColumn(event.target.value); setFeatureColumns((current) => current.filter((column) => column !== event.target.value)); }}>{inspection.numericColumns.map((column) => <option key={column}>{column}</option>)}</select><small>Realized after the observation date</small></label>
                <label>Point-in-time availability<select value={availabilityColumn} onChange={(event) => { invalidateAudit(); setAvailabilityColumn(event.target.value); setFeatureColumns((current) => current.filter((column) => column !== event.target.value)); }}><option value="">Not supplied</option>{inspection.dateColumns.filter((column) => column !== dateColumn).map((column) => <option key={column}>{column}</option>)}</select><small>Optional: publication or availability date</small></label>
                <label>Data frequency<select value={frequency} onChange={(event) => { invalidateAudit(); const next = event.target.value as DataFrequency; setFrequency(next); setTargetHorizonPeriods(FREQUENCY_OPTIONS[next].horizons[0]); }}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option></select><small>Auto-detected; override if needed</small></label>
                <label>Target horizon<select value={targetHorizonPeriods} onChange={(event) => { invalidateAudit(); setTargetHorizonPeriods(Number(event.target.value)); }}>{FREQUENCY_OPTIONS[frequency].horizons.map((periods) => <option key={periods} value={periods}>{periods} {frequency} period{periods === 1 ? "" : "s"}</option>)}</select><small>Declared forward-return horizon</small></label>
                <label>Candidate budget<select value={candidateBudget} onChange={(event) => setCandidateBudget(Number(event.target.value))}><option value={100}>100 · quick</option><option value={250} disabled={!workloadFits(inspection.rowCount, featureColumns.length, 250)}>250 · standard</option><option value={500} disabled={!workloadFits(inspection.rowCount, featureColumns.length, 500)}>500 · extended</option></select><small>Automatically bounded by panel size</small></label>
                <label>Redundancy threshold<select value={correlationThreshold} onChange={(event) => setCorrelationThreshold(Number(event.target.value))}><option value={0.7}>0.70 · strict</option><option value={0.8}>0.80 · standard</option><option value={0.9}>0.90 · permissive</option></select><small>Train exposure correlation</small></label>
                <label>Transaction cost<select value={transactionCostBps} onChange={(event) => setTransactionCostBps(Number(event.target.value))}><option value={0}>0 bps · frictionless</option><option value={10}>10 bps · liquid</option><option value={25}>25 bps · standard</option><option value={50}>50 bps · conservative</option></select><small>One-way cost per unit of turnover</small></label>
                <div className="split-contract"><span>PURGED TIME SPLIT</span><strong>60 / 20 / 20</strong><small>Train · Selection · Calibration</small></div>
              </div>

              <div className="feature-picker">
                <div><span>NUMERIC FEATURES</span><b>{featureColumns.length} selected · {availableFeatureColumns.length} available · maximum 50</b></div>
                <div className="feature-grid">
                  {availableFeatureColumns.map((column) => (
                    <label className={featureColumns.includes(column) ? "selected" : ""} key={column}>
                      <input type="checkbox" checked={featureColumns.includes(column)} onChange={() => toggleFeature(column)} />
                      <span>{compactColumn(column)}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className={`ai-proposal-panel ${aiProposalState}`}>
                <div><span>OPTIONAL IN-BROWSER AI</span><strong>Propose candidate structures</strong><p>{aiProposalMessage}</p></div>
                <button type="button" disabled={!featureColumns.length || !["ready", "complete"].includes(aiProposalState)} onClick={() => void requestAIProposals()}>{aiProposalState === "running" ? "Proposing…" : aiProposals.length ? "Refresh proposals" : "Use browser AI"}</button>
                <small>The open model runs inside this webpage and needs no account or API key. Its first use downloads roughly 400 MB and caches it in the browser. Only selected feature labels enter the model; rows, targets, validation evidence, code, and decision authority remain outside it.</small>
              </div>

              <button className="private-audit" type="button" disabled={!canAudit} onClick={runAudit}><span>{phase === "auditing" ? "Auditing dataset…" : audit ? "Re-run data audit" : "Audit dataset"}</span><b>CHECK →</b></button>

              {audit && (
                <div className={`audit-report ${audit.passed ? "passed" : "blocked"}`}>
                  <div className="audit-report-head"><div><span>{audit.passed ? "DATA AUDIT PASSED" : "DATA AUDIT BLOCKED"}</span><h3>{audit.passed ? "Research panel is ready for discovery" : `${audit.blockers.length} blocking issue${audit.blockers.length === 1 ? "" : "s"} must be resolved`}</h3></div><p>{audit.configuration.availabilityColumn ? `Availability checked with ${audit.configuration.availabilityColumn}.` : "No availability date supplied; the audit cannot independently verify when features became known."}</p></div>
                  <div className="audit-metrics">
                    <div><span>Complete rows</span><strong>{audit.summary.completeRows.toLocaleString()}</strong></div>
                    <div><span>Valid periods</span><strong>{audit.dateCoverage.validPeriods}</strong></div>
                    <div><span>Duplicate keys</span><strong>{audit.summary.duplicateKeys}</strong></div>
                    <div><span>Future availability</span><strong>{audit.summary.futureAvailabilityRows}</strong></div>
                  </div>
                  <div className="audit-checks">
                    {audit.checks.map((check) => <div className="audit-check" key={check.id}><span className={check.status.toLowerCase()}>{check.status}</span><div><strong>{check.label}</strong><p>{check.detail}</p></div></div>)}
                  </div>
                </div>
              )}

              <button className="private-run" type="button" disabled={!canRun} onClick={runDiscovery}><span>{phase === "running" ? "Discovery in progress…" : audit?.passed ? "Run private factor discovery" : "Complete data audit to unlock discovery"}</span><b>↗</b></button>
            </div>
          )}

          {phase === "error" && <div className="upload-error" role="alert"><strong>Check the dataset</strong><p>{error}</p></div>}

          {result && phase === "complete" && (
            <div className="private-results">
              <div className="private-result-head">
                <div><span className={result.assessment.tier}>{result.assessment.label}</span><h3>Your private discovery result</h3><p>{stage}</p></div>
                <div className="result-run-id"><span>{result.schemaVersion}</span><b>{new Date(result.generatedAt).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</b></div>
              </div>
              <div className={`evidence-assessment ${result.assessment.tier}`}>
                <div><span>EVIDENCE, NOT A BINARY SEARCH RESULT</span><strong>{result.assessment.headline}</strong></div>
                <p>{result.assessment.detail}</p>
              </div>
              <div className="private-result-metrics">
                <div><span>Generated</span><strong>{result.summary.generatedCandidates}</strong></div>
                <div><span>Train qualified</span><strong>{result.summary.trainQualified}</strong></div>
                <div><span>Pruned set</span><strong>{result.summary.correlationPruned}</strong></div>
                <div><span>Active ensemble</span><strong>{result.summary.activeComponents}</strong></div>
                <div><span>Calibration RankIC</span><strong>{result.summary.calibrationMeanRankIC.toFixed(4)}</strong></div>
                <div><span>Positive periods</span><strong>{(result.summary.calibrationHitRate * 100).toFixed(1)}%</strong></div>
              </div>
              <div className="resource-summary"><span>STREAMING CSV</span><p>Selected columns only · estimated working set {result.resourceUse.estimatedWorkingSetMB.toFixed(1)} MB · {(result.resourceUse.candidateObservations / 1_000_000).toFixed(1)}M discovery + {(result.resourceUse.estimatedRollingCandidateObservations / 1_000_000).toFixed(1)}M full-year walk-forward observations</p></div>
              <div className="result-exports">
                <div><span>REPRODUCIBILITY EXPORTS</span><strong>Take the evidence with you</strong><p>Every export is generated locally from this exact run.</p></div>
                <div><button type="button" onClick={downloadResult}>Research JSON</button><button type="button" onClick={downloadFactorDefinitions}>Factor definition CSV</button><button type="button" onClick={downloadWalkForwardEvidence}>Walk-forward CSV</button><button type="button" onClick={downloadValidationReport}>Validation report</button></div>
              </div>
              <div className="validation-evidence">
                <div className="result-section-head result-section-head-compact"><div><span>CANDIDATE DIAGNOSTICS</span><h4>Why transformations did not advance</h4></div><p>{result.screeningDiagnostics.explanation}</p></div>
                <div className="diagnostic-grid">
                  <div><strong>{result.screeningDiagnostics.insufficientHistory}</strong><span>Insufficient usable history</span><p>Too few Train periods remained after missing values or required lookbacks.</p></div>
                  <div><strong>{result.screeningDiagnostics.weakTrainSignal}</strong><span>Weak Train relationship</span><p>Absolute mean RankIC was below 0.002; the cross-sectional ordering was effectively negligible.</p></div>
                  <div><strong>{result.screeningDiagnostics.redundantCandidates}</strong><span>Redundant exposure</span><p>The candidate was too correlated with a stronger retained exposure at the chosen redundancy threshold.</p></div>
                  <div><strong>{result.screeningDiagnostics.nonPositiveSelectionEdge}</strong><span>No positive Selection edge</span><p>The Train direction did not carry into the separate Selection sample above the 0.001 edge floor.</p></div>
                  <div><strong>{result.screeningDiagnostics.multiplicityFailed}</strong><span>Multiplicity not survived</span><p>The evidence did not remain significant after Holm correction for the family of tests.</p></div>
                  <div><strong>{result.screeningDiagnostics.distinctCandidates}</strong><span>Distinct candidates retained</span><p>These advanced to Selection; retention is not the same as validation.</p></div>
                </div>
                <div className="validation-evidence-head"><div><span>INFERENCE &amp; IMPLEMENTATION</span><h4>Purged, multiplicity-adjusted, and cost-aware</h4></div><p>{result.validation.purge.reason}</p></div>
                <div className="validation-evidence-grid">
                  <div><span>Purged periods</span><strong>{result.periods.purged}</strong><small>{result.validation.purge.periodsPerBoundary} per boundary</small></div>
                  <div><span>Holm family</span><strong>{result.validation.multipleTesting.selectionFamilySize}</strong><small>{result.validation.multipleTesting.selectionCandidatesPassing10Pct} candidates pass at 10%</small></div>
                  <div><span>Calibration HAC t</span><strong>{Number.isFinite(result.validation.calibrationInference.meanRankIC.tStatistic) ? result.validation.calibrationInference.meanRankIC.tStatistic.toFixed(2) : "—"}</strong><small>lag {result.validation.calibrationInference.meanRankIC.hacLags}</small></div>
                  <div><span>Adjusted p</span><strong>{Math.max(result.validation.calibrationInference.adjustedMeanPvalue, result.validation.calibrationInference.adjustedDirectionalPvalue).toFixed(3)}</strong><small>joint two-test family</small></div>
                  <div><span>Gross spread</span><strong>{(result.validation.portfolio.gross.mean * 100).toFixed(2)}%</strong><small>top − bottom 20%</small></div>
                  <div><span>Net spread</span><strong>{(result.validation.portfolio.net.mean * 100).toFixed(2)}%</strong><small>after {result.validation.portfolio.transactionCostBps} bps</small></div>
                  <div><span>Turnover</span><strong>{(result.validation.portfolio.meanTurnover * 100).toFixed(1)}%</strong><small>one-way notional</small></div>
                  <div><span>Net-return p</span><strong>{result.validation.portfolio.net.pValue.toFixed(3)}</strong><small>HAC one-sided</small></div>
                </div>
                <div className="validation-evidence-head validation-evidence-head-secondary"><div><span>FREQUENCY-AWARE WALK-FORWARD</span><h4>Re-estimated once per year</h4></div><p>{result.validation.walkForward.trainPeriods} Train → purge → {result.validation.walkForward.selectionPeriods} Selection → purge → {result.validation.walkForward.calibrationPeriods} Calibration → purge → {result.validation.walkForward.testBlockPeriods} frozen {result.mapping.frequency} test periods. Failed Calibration blocks hold cash for the full year.</p></div>
                <div className="validation-evidence-grid">
                  <div><span>Full-year blocks</span><strong>{result.validation.walkForward.evaluatedBlocks}</strong><small>{result.validation.walkForward.evaluatedPeriods}/{result.validation.walkForward.eligiblePeriods} eligible {result.mapping.frequency} periods evaluated{result.validation.walkForward.excludedLeadingPartialPeriods > 0 ? ` · ${result.validation.walkForward.excludedLeadingPartialPeriods} leading partial periods excluded` : ""}{result.validation.walkForward.truncated ? ` · latest ${result.validation.walkForward.maximumEvaluatedBlocks} blocks within budget` : ""}</small></div>
                  <div><span>Deployed blocks</span><strong>{result.validation.walkForward.deployedBlocks}</strong><small>{result.validation.walkForward.cashBlocks} full-year cash blocks</small></div>
                  <div><span>OOS RankIC</span><strong>{result.validation.walkForward.oosRankIC.mean.toFixed(4)}</strong><small>{(result.validation.walkForward.positiveOosRankICShare * 100).toFixed(1)}% positive</small></div>
                  <div><span>Net OOS spread</span><strong>{(result.validation.walkForward.net.mean * 100).toFixed(2)}%</strong><small>including no-trade periods</small></div>
                  <div><span>OOS gross spread</span><strong>{(result.validation.walkForward.gross.mean * 100).toFixed(2)}%</strong><small>top − bottom 20%</small></div>
                  <div><span>OOS turnover</span><strong>{(result.validation.walkForward.meanTurnover * 100).toFixed(1)}%</strong><small>entries, rebalances, and exits</small></div>
                  <div><span>OOS net p</span><strong>{result.validation.walkForward.net.pValue.toFixed(3)}</strong><small>HAC one-sided</small></div>
                  <div><span>Candidate dictionary</span><strong>{result.validation.walkForward.candidateDictionarySize}</strong><small>fixed before full-year tests</small></div>
                </div>
              </div>
              <section className="result-proof" aria-labelledby="result-proof-title">
                <div className="result-section-head"><div><span>PERFORMANCE TRACE</span><h4 id="result-proof-title">See what happened in every untouched period</h4></div><p>Net wealth includes the selected trading cost, no-trade periods, entries, rebalances, and exits.</p></div>
                <div className="result-charts"><WalkForwardWealthChart windows={result.validation.walkForward.periods} /><RankICTimeline windows={result.validation.walkForward.periods} /></div>
                <div className="result-section-head result-section-head-compact"><div><span>DECISION LEDGER</span><h4>Every gate, with its reason</h4></div><p>The overall decision passes only when all seven gates pass.</p></div>
                <div className="validation-gates">
                  {result.validation.gates.map((gate) => <div className={gate.passed ? "passed" : "failed"} key={gate.id}><span>{gate.passed ? "PASS" : "FAIL"}</span><div><strong>{gate.label}</strong><p>{gate.detail}</p>{!gate.passed && <p className="gate-explanation"><b>Why this matters:</b> {gateInterpretation(gate.id)}</p>}</div></div>)}
                </div>
                <div className="result-section-head result-section-head-compact"><div><span>FULL-YEAR BLOCK LEDGER</span><h4>Frozen-model out-of-sample evidence</h4></div><p>Each model is selected once, frozen, and carried through one full year of {result.mapping.frequency} test periods.</p></div>
                <div className="private-result-table-wrap">
                  <table className="private-result-table walk-forward-table">
                    <thead><tr><th>Block</th><th>Test period</th><th>Decision</th><th>Components</th><th>Mean OOS RankIC</th><th>Positive periods</th><th>Mean gross</th><th>Mean turnover</th><th>Mean net</th></tr></thead>
                    <tbody>{result.validation.walkForward.blocks.map((block) => <tr key={block.block}><td>{String(block.block).padStart(2, "0")}</td><td>{block.testStart.slice(0, 7)} → {block.testEnd.slice(0, 7)}</td><td><span className={block.calibrationPassed ? "window-deployed" : "window-cash"}>{block.calibrationPassed ? "DEPLOY" : "CASH"}</span></td><td>{block.activeComponents}</td><td>{block.meanOosRankIC === null ? "—" : block.meanOosRankIC.toFixed(4)}</td><td>{block.meanOosRankIC === null ? "—" : `${(block.positiveOosRankICShare * 100).toFixed(1)}%`}</td><td>{(block.meanGrossReturn * 100).toFixed(2)}%</td><td>{(block.meanTurnover * 100).toFixed(1)}%</td><td className={block.meanNetReturn >= 0 ? "return-positive" : "return-negative"}>{(block.meanNetReturn * 100).toFixed(2)}%</td></tr>)}</tbody>
                  </table>
                </div>
              </section>
                <div className="result-section-head result-section-head-components"><div><span>DISCOVERED FORMULA</span><h4>Reproducible candidate definition</h4></div><p>Direction and weight are fixed for the reported Calibration ensemble. The evidence tier above determines whether it is validated, regime-dependent, or exploratory.</p></div>
              <div className="private-result-table-wrap">
                <table className="private-result-table">
                  <thead><tr><th>Rank</th><th>Frozen component</th><th>Family</th><th>Lookback</th><th>Direction</th><th>Weight</th><th>Train |RankIC|</th><th>Selection RankIC</th><th>Holm p</th></tr></thead>
                  <tbody>{result.components.map((component) => <tr key={component.rank}><td>{String(component.rank).padStart(2, "0")}</td><td>{compactColumn(component.expression)}</td><td>{component.family}</td><td>{component.lookbackPeriods === 0 ? "current" : `${component.lookbackPeriods}m`}</td><td>{component.direction > 0 ? "+1" : "−1"}</td><td>{(component.weight * 100).toFixed(2)}%</td><td>{component.train.absMeanRankIC.toFixed(4)}</td><td>{component.selection.meanRankIC.toFixed(4)}</td><td>{Math.max(component.selection.adjustedMeanPvalue, component.selection.adjustedDirectionalPvalue).toFixed(3)}</td></tr>)}</tbody>
                </table>
              </div>
              <div className="private-result-note"><strong>Research evidence, not a profit claim.</strong><p>The engine reports purged inference, joint Holm correction, cost-adjusted portfolios, and frequency-aware full-year out-of-sample evidence. An external untouched holdout is still required before making an investment-performance claim.</p></div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
