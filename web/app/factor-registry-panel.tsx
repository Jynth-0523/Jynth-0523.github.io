"use client";

import { useMemo, useState } from "react";
import { factorComponents, release } from "./platform-data";

type Operation = (typeof factorComponents)[number]["operation"];
type WeightFilter = "all" | "active" | "zero";

const operationLabels: Record<Operation, string> = {
  normalized_difference: "Normalized difference",
  difference: "Difference",
  product: "Product",
  identity: "Single signal",
  ratio: "Ratio",
};

function signalName(value: string) {
  return value.replaceAll("_", " ");
}

function expression(operation: Operation, left: string, right: string) {
  if (operation === "identity") return signalName(left);
  if (operation === "normalized_difference") return `z(${signalName(left)} − ${signalName(right)})`;
  const symbol = operation === "difference" ? "−" : operation === "product" ? "×" : "÷";
  return `${signalName(left)} ${symbol} ${signalName(right)}`;
}

export function FactorRegistryPanel() {
  const [operation, setOperation] = useState<Operation | "all">("all");
  const [weightFilter, setWeightFilter] = useState<WeightFilter>("all");
  const [expanded, setExpanded] = useState(false);

  const operations = useMemo(
    () => Array.from(new Set(factorComponents.map((item) => item.operation))) as Operation[],
    [],
  );

  const filtered = useMemo(
    () => factorComponents.filter((item) => {
      const operationMatch = operation === "all" || item.operation === operation;
      const weightMatch = weightFilter === "all" || (weightFilter === "active" ? item.active : !item.active);
      return operationMatch && weightMatch;
    }),
    [operation, weightFilter],
  );

  const visible = expanded ? filtered : filtered.slice(0, 12);

  return (
    <section className="registry-section section" id="registry">
      <div className="section-intro">
        <div>
          <span className="section-index">04 / FACTOR REGISTRY</span>
          <h2>A recorded development snapshot.</h2>
        </div>
        <p>
          These are real outputs copied from the stored research artifacts—not example rows or
          results produced from a visitor&apos;s upload. They remain development evidence, not validated strategies.
        </p>
      </div>

      <div className="registry-provenance">
        <div><span>UNIVERSE</span><strong>{release.universe}</strong></div>
        <div><span>DATA &amp; LINKING</span><strong>{release.dataSources}</strong></div>
        <div><span>SAMPLE</span><strong>{release.developmentPeriod}</strong></div>
        <div><span>FREQUENCY</span><strong>{release.frequency}</strong></div>
        <div><span>RESEARCH ROLES</span><strong>Train {release.trainPeriod}<br />Selection {release.selectionPeriod}<br />Calibration {release.calibrationPeriod}</strong></div>
        <div><span>OBSERVATIONS</span><strong>{release.factorObservations.toLocaleString()} derived factor rows</strong></div>
        <div><span>INTEGRITY</span><strong>{release.duplicateStableKeys} duplicate PERMNO–POINTDATE keys · artifact hashes verified</strong></div>
        <div><span>OUTCOME</span><strong>Calibration soft gate passed · cost-aware gate failed · no final model</strong></div>
      </div>

      <div className="registry-note">
        <strong>Interpretation matters.</strong>
        <p>These are 30 inputs to one frozen development ensemble—not 30 independently calibrated trading strategies.</p>
        <span>25 active · 5 zero-weight</span>
      </div>

      <div className="registry-controls">
        <div className="filter-set" aria-label="Filter by weight status">
          {(["all", "active", "zero"] as const).map((filter) => (
            <button
              type="button"
              key={filter}
              className={weightFilter === filter ? "selected" : ""}
              onClick={() => { setWeightFilter(filter); setExpanded(false); }}
            >
              {filter === "all" ? "All weights" : filter === "active" ? "Active only" : "Zero-weight"}
            </button>
          ))}
        </div>
        <div className="filter-set operation-set" aria-label="Filter by transform">
          <button type="button" className={operation === "all" ? "selected" : ""} onClick={() => { setOperation("all"); setExpanded(false); }}>All transforms</button>
          {operations.map((item) => (
            <button type="button" key={item} className={operation === item ? "selected" : ""} onClick={() => { setOperation(item); setExpanded(false); }}>
              {operationLabels[item]}
            </button>
          ))}
        </div>
      </div>

      <div className="registry-table-wrap">
        <table className="registry-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Component expression</th>
              <th>Transform</th>
              <th>Sign</th>
              <th>Weight</th>
              <th>|RankIC|</th>
              <th>|ICIR|</th>
              <th>Stability</th>
              <th>Coverage</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((item) => (
              <tr key={item.factorId} className={item.active ? "" : "zero-row"}>
                <td className="rank-cell">{String(item.rank).padStart(2, "0")}</td>
                <td className="expression-cell">
                  <strong>{expression(item.operation, item.left, item.right)}</strong>
                  <code>{item.factorId}</code>
                </td>
                <td>{operationLabels[item.operation]}</td>
                <td className="numeric">{item.direction > 0 ? "+1" : "−1"}</td>
                <td className="numeric weight-cell">{(item.weight * 100).toFixed(2)}%</td>
                <td className="numeric">{item.rankIC.toFixed(4)}</td>
                <td className="numeric">{item.icir.toFixed(4)}</td>
                <td className="numeric">{item.stability.toFixed(4)}</td>
                <td className="numeric">{(item.coverage * 100).toFixed(1)}%</td>
                <td><span className={`component-status ${item.active ? "active" : "zero"}`}>{item.active ? "Ensemble input" : "Zero weight"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length > 12 && (
        <button type="button" className="registry-expand" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Show fewer components" : `Show all ${filtered.length} components`}
        </button>
      )}

      <div className="metric-definitions">
        <p><b>|RankIC|</b> Absolute mean monthly cross-sectional rank correlation in Train.</p>
        <p><b>|ICIR|</b> Absolute information-coefficient ratio in Train.</p>
        <p><b>Stability</b> Subperiod consistency score used during screening.</p>
        <p><b>Coverage</b> Median share of eligible observations with a valid signal.</p>
      </div>
      <p className="registry-source-note">Source note: the table reproduces frozen derived metrics from the stored development artifacts. Licensed CRSP, Compustat, and CCM source records are not redistributed.</p>
    </section>
  );
}
