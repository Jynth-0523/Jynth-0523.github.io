import type { AIProposal, Candidate, Period, Metrics } from "./worker-types";
import { average, standardDeviation, periodRankIC } from "./statistics";
function fail(message: string): never { throw new Error(message); }

export function candidateValue(candidate: Candidate, left: number, right: number) {
  if (candidate.operation === "identity") return left;
  if (candidate.operation === "square") return Math.sign(left) * left * left;
  if (candidate.operation === "difference") return left - right;
  if (candidate.operation === "product") return left * right;
  return left / (Math.abs(right) + 0.25);
}

export function alignedHistoricalValue(period: Period, featureIndex: number, entityIndex: number, lag: number) {
  let cursor: Period | null = period;
  let cursorEntityIndex = entityIndex;
  for (let step = 0; step < lag; step += 1) {
    if (!cursor?.previousPeriod || !cursor.previousEntityIndex) return Number.NaN;
    cursorEntityIndex = cursor.previousEntityIndex[cursorEntityIndex];
    cursor = cursor.previousPeriod;
    if (cursorEntityIndex < 0) return Number.NaN;
  }
  return cursor.featureColumns[featureIndex][cursorEntityIndex];
}

export function candidateObservation(candidate: Candidate, period: Period, entityIndex: number) {
  const left = period.featureColumns[candidate.leftIndex];
  const right = candidate.rightIndex >= 0 ? period.featureColumns[candidate.rightIndex] : null;
  const current = left[entityIndex];
  if (candidate.operation === "lag1") return alignedHistoricalValue(period, candidate.leftIndex, entityIndex, 1);
  if (candidate.operation === "change1" || candidate.operation === "growth1") {
    const previous = alignedHistoricalValue(period, candidate.leftIndex, entityIndex, 1);
    if (!Number.isFinite(previous)) return Number.NaN;
    return candidate.operation === "change1" ? current - previous : (current - previous) / (Math.abs(previous) + 0.25);
  }
  if (candidate.operation === "mean3" || candidate.operation === "volatility3") {
    const history = [
      current,
      alignedHistoricalValue(period, candidate.leftIndex, entityIndex, 1),
      alignedHistoricalValue(period, candidate.leftIndex, entityIndex, 2),
    ];
    if (!history.every(Number.isFinite)) return Number.NaN;
    if (candidate.operation === "mean3") return average(history);
    return standardDeviation(history);
  }
  return candidateValue(candidate, current, right?.[entityIndex] ?? 0);
}

export function candidateSeries(candidate: Candidate, period: Period) {
  const values = new Array<number>(period.observationCount);
  for (let index = 0; index < period.observationCount; index += 1) {
    values[index] = candidateObservation(candidate, period, index);
  }
  return values;
}

export function proposalCandidate(proposal: AIProposal, featureColumns: string[]): Candidate {
  const leftIndex = featureColumns.indexOf(proposal.left_feature);
  const rightIndex = proposal.right_feature === null ? -1 : featureColumns.indexOf(proposal.right_feature);
  const binaryOperations = new Set<Candidate["operation"]>(["difference", "product", "ratio"]);
  if (leftIndex < 0 || !proposal.operation || proposal.decision_authority !== false) fail("An AI proposal failed deterministic validation.");
  if (binaryOperations.has(proposal.operation)) {
    if (rightIndex < 0 || rightIndex === leftIndex) fail("An AI binary proposal failed deterministic validation.");
  } else if (proposal.right_feature !== null) fail("An AI unary proposal failed deterministic validation.");
  const family: Candidate["family"] = proposal.operation === "identity"
    ? "primitive"
    : proposal.operation === "square"
      ? "nonlinear"
      : binaryOperations.has(proposal.operation)
        ? "interaction"
        : "temporal";
  const complexity = proposal.operation === "identity" ? 1
    : ["square", "lag1", "change1", "difference", "product"].includes(proposal.operation) ? 2
      : ["growth1", "mean3", "ratio"].includes(proposal.operation) ? 3 : 4;
  const lookbackPeriods = proposal.operation === "mean3" || proposal.operation === "volatility3" ? 2
    : ["lag1", "change1", "growth1"].includes(proposal.operation) ? 1 : 0;
  const left = featureColumns[leftIndex];
  const right = rightIndex >= 0 ? featureColumns[rightIndex] : "";
  const expressions: Record<AIProposal["operation"], string> = {
    identity: left,
    square: `signed_square(${left})`,
    lag1: `lag_1(${left})`,
    change1: `change_1(${left})`,
    growth1: `growth_1(${left})`,
    mean3: `rolling_mean_3(${left})`,
    volatility3: `rolling_volatility_3(${left})`,
    difference: `${left} − ${right}`,
    product: `${left} × ${right}`,
    ratio: `${left} ÷ ${right}`,
  };
  return {
    id: `ai_${proposal.operation}_${leftIndex}_${rightIndex}`,
    operation: proposal.operation,
    family,
    complexity,
    lookbackPeriods,
    source: "ai-proposed",
    leftIndex,
    rightIndex,
    expression: expressions[proposal.operation],
  };
}

export function generateCandidates(featureColumns: string[], budget: number, aiProposals: AIProposal[] = []) {
  const candidates: Candidate[] = [];
  const addUnaryFamily = (operation: Candidate["operation"], family: Candidate["family"], complexity: number, lookbackPeriods: number, render: (feature: string) => string) => {
    for (let index = 0; index < featureColumns.length && candidates.length < budget; index += 1) {
      candidates.push({
        id: `${operation}_${index}`,
        operation,
        family,
        complexity,
        lookbackPeriods,
        source: "deterministic",
        leftIndex: index,
        rightIndex: -1,
        expression: render(featureColumns[index]),
      });
    }
  };
  addUnaryFamily("identity", "primitive", 1, 0, (feature) => feature);
  const unaryAllowance = Math.min(6 * featureColumns.length, Math.ceil(Math.max(0, budget - candidates.length) * 0.6));
  const unaryStart = candidates.length;
  const unaryOperations = [
    ["lag1", "temporal", 2, 1, (feature: string) => `lag_1(${feature})`],
    ["change1", "temporal", 2, 1, (feature: string) => `change_1(${feature})`],
    ["mean3", "temporal", 3, 2, (feature: string) => `rolling_mean_3(${feature})`],
    ["square", "nonlinear", 2, 0, (feature: string) => `signed_square(${feature})`],
    ["growth1", "temporal", 3, 1, (feature: string) => `growth_1(${feature})`],
    ["volatility3", "temporal", 4, 2, (feature: string) => `rolling_volatility_3(${feature})`],
  ] as const;
  for (let featureOffset = 0; featureOffset < featureColumns.length && candidates.length - unaryStart < unaryAllowance; featureOffset += 1) {
    for (let operationIndex = 0; operationIndex < unaryOperations.length && candidates.length - unaryStart < unaryAllowance; operationIndex += 1) {
      const [operation, family, complexity, lookbackPeriods, render] = unaryOperations[operationIndex];
      const featureIndex = (featureOffset + operationIndex * Math.ceil(featureColumns.length / unaryOperations.length)) % featureColumns.length;
      candidates.push({
        id: `${operation}_${featureIndex}`,
        operation,
        family,
        complexity,
        lookbackPeriods,
        source: "deterministic",
        leftIndex: featureIndex,
        rightIndex: -1,
        expression: render(featureColumns[featureIndex]),
      });
    }
  }
  const operations: Candidate["operation"][] = ["difference", "product", "ratio"];
  for (let left = 0; left < featureColumns.length && candidates.length < budget; left += 1) {
    for (let right = left + 1; right < featureColumns.length && candidates.length < budget; right += 1) {
      for (const operation of operations) {
        if (candidates.length >= budget) break;
        const symbol = operation === "difference" ? "−" : operation === "product" ? "×" : "÷";
        candidates.push({
          id: `${operation}_${left}_${right}`,
          operation,
          family: "interaction",
          complexity: operation === "ratio" ? 3 : 2,
          lookbackPeriods: 0,
          source: "deterministic",
          leftIndex: left,
          rightIndex: right,
          expression: `${featureColumns[left]} ${symbol} ${featureColumns[right]}`,
        });
      }
    }
  }
  const aiCandidates = aiProposals.slice(0, 12).map((proposal) => proposalCandidate(proposal, featureColumns));
  const uniqueAi = aiCandidates.filter((candidate, index, values) => values.findIndex((item) => item.operation === candidate.operation && item.leftIndex === candidate.leftIndex && item.rightIndex === candidate.rightIndex) === index);
  const aiIdentities = new Set(uniqueAi.map((candidate) => `${candidate.operation}:${candidate.leftIndex}:${candidate.rightIndex}`));
  const deterministic = candidates.filter((candidate) => !aiIdentities.has(`${candidate.operation}:${candidate.leftIndex}:${candidate.rightIndex}`));
  return [...uniqueAi, ...deterministic].slice(0, budget);
}

export function evaluate(candidate: Candidate, periods: Period[]): Metrics {
  const icSeries = periods.map((period) => periodRankIC(candidateSeries(candidate, period), period)).filter(Number.isFinite);
  if (icSeries.length === 0) {
    return { meanRankIC: 0, absMeanRankIC: 0, icir: 0, hitRate: 0, stability: 0, validPeriods: 0, icSeries: [] };
  }
  const meanRankIC = average(icSeries);
  const deviation = standardDeviation(icSeries);
  const positiveShare = icSeries.filter((value) => value > 0).length / icSeries.length;
  return {
    meanRankIC,
    absMeanRankIC: Math.abs(meanRankIC),
    icir: deviation > 1e-12 ? meanRankIC / deviation : 0,
    hitRate: Math.max(positiveShare, 1 - positiveShare),
    stability: Math.max(positiveShare, 1 - positiveShare),
    validPeriods: icSeries.length,
    icSeries,
  };
}

