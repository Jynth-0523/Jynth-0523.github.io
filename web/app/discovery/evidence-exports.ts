import type { DiscoveryResult } from "./workspace-types";

export function csvCell(value: string | number | boolean | null) {
  const text = value === null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function downloadText(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function factorDefinitionCsv(result: DiscoveryResult) {
  const rows: Array<Array<string | number | boolean | null>> = [["rank", "expression", "operation", "family", "complexity", "lookback_periods", "source", "direction", "weight", "train_abs_rank_ic", "selection_rank_ic", "holm_adjusted_p"]];
  result.components.forEach((component) => rows.push([
    component.rank,
    component.expression,
    component.operation,
    component.family,
    component.complexity,
    component.lookbackPeriods,
    component.source,
    component.direction,
    component.weight,
    component.train.absMeanRankIC,
    component.selection.meanRankIC,
    Math.max(component.selection.adjustedMeanPvalue, component.selection.adjustedDirectionalPvalue),
  ]));
  return `${rows.map((row) => row.map((value) => csvCell(value)).join(",")).join("\n")}\n`;
}

export function walkForwardCsv(result: DiscoveryResult) {
  let grossWealth = 1;
  let netWealth = 1;
  const rows: Array<Array<string | number | boolean | null>> = [["full_year_block", "test_date", "calibration_passed", "active_components", "oos_rank_ic", "gross_return", "turnover", "net_return", "gross_wealth", "net_wealth"]];
  result.validation.walkForward.periods.forEach((window) => {
    grossWealth *= 1 + window.grossReturn;
    netWealth *= 1 + window.netReturn;
    rows.push([window.block, window.testDate, window.calibrationPassed, window.activeComponents, window.oosRankIC, window.grossReturn, window.turnover, window.netReturn, grossWealth, netWealth]);
  });
  return `${rows.map((row) => row.map((value) => csvCell(value)).join(",")).join("\n")}\n`;
}

export function validationReport(result: DiscoveryResult) {
  const decision = result.assessment.label;
  const gateRows = result.validation.gates.map((gate) => `| ${gate.passed ? "PASS" : "FAIL"} | ${gate.label} | ${gate.detail.replaceAll("|", "\\|")} |`).join("\n");
  const componentRows = result.components.map((component) => `| ${component.rank} | ${component.expression.replaceAll("|", "\\|")} | ${component.direction > 0 ? "+1" : "-1"} | ${(component.weight * 100).toFixed(2)}% | ${component.train.absMeanRankIC.toFixed(4)} | ${component.selection.meanRankIC.toFixed(4)} |`).join("\n");
  return `# Factor Discovery Validation Report

**Decision:** ${decision}  
**Generated:** ${result.generatedAt}  
**Source:** ${result.source.filename} (${result.source.rowCount.toLocaleString()} rows)  
**Protocol:** ${result.validation.protocol}  
**Data frequency:** ${result.mapping.frequency}  
**Target horizon:** ${result.mapping.targetHorizonPeriods} period(s)  
**Transaction cost:** ${result.validation.portfolio.transactionCostBps} bps

## Evidence assessment

**${result.assessment.headline}**  
${result.assessment.detail}

## Validation gates

| Status | Gate | Evidence |
|---|---|---|
${gateRows}

## Full-year refit out-of-sample evidence

- Full-year refit blocks: ${result.validation.walkForward.evaluatedBlocks}
- Out-of-sample periods: ${result.validation.walkForward.evaluatedPeriods}
- Deployed full-year blocks: ${result.validation.walkForward.deployedBlocks}
- Mean OOS RankIC: ${result.validation.walkForward.oosRankIC.mean.toFixed(4)}
- Mean gross spread: ${(result.validation.walkForward.gross.mean * 100).toFixed(2)}%
- Mean net spread: ${(result.validation.walkForward.net.mean * 100).toFixed(2)}%
- Mean one-way turnover: ${(result.validation.walkForward.meanTurnover * 100).toFixed(1)}%

## Frozen factor definition

| Rank | Expression | Direction | Weight | Train abs RankIC | Selection RankIC |
|---|---|---|---|---|---|
${componentRows}

## Interpretation boundary

This report is research evidence, not an investment-performance claim or investment advice. An external untouched holdout remains required before making a performance claim.
`;
}

