import type { Candidate, Period } from "./worker-types";
import { candidateObservation } from "./candidate-formulas";
import { average, oneSidedMeanInference } from "./statistics";

export function candidateVector(candidate: Candidate, periods: Period[], limit = 10_000) {
  const values: number[] = [];
  for (const period of periods) {
    for (let index = 0; index < period.observationCount; index += 1) {
      values.push(candidateObservation(candidate, period, index));
      if (values.length >= limit) return values;
    }
  }
  return values;
}

export function ensembleScores(
  period: Period,
  weighted: Array<{ candidate: Candidate; direction: number; weight: number }>,
) {
  const score = new Array<number>(period.observationCount).fill(0);
  const availableWeight = new Array<number>(period.observationCount).fill(0);
  for (const item of weighted) {
    for (let index = 0; index < period.observationCount; index += 1) {
      const value = candidateObservation(item.candidate, period, index);
      if (!Number.isFinite(value)) continue;
      score[index] += item.weight * item.direction * value;
      availableWeight[index] += item.weight;
    }
  }
  for (let index = 0; index < score.length; index += 1) {
    score[index] = availableWeight[index] >= 0.5 ? score[index] / availableWeight[index] : Number.NaN;
  }
  return score;
}

export function portfolioPosition(
  period: Period,
  weighted: Array<{ candidate: Candidate; direction: number; weight: number }>,
) {
  if (weighted.length === 0) return { weights: new Map<string, number>(), grossReturn: 0 };
  const scores = ensembleScores(period, weighted);
  const order = scores.map((value, index) => ({ value, index })).filter((item) => Number.isFinite(item.value)).sort((left, right) => left.value - right.value);
  if (order.length < 5) return { weights: new Map<string, number>(), grossReturn: 0 };
  const tailCount = Math.max(1, Math.floor(order.length * 0.2));
  const bottom = order.slice(0, tailCount).map((item) => item.index);
  const top = order.slice(-tailCount).map((item) => item.index);
  const grossReturn = average(top.map((index) => period.targetValues[index])) - average(bottom.map((index) => period.targetValues[index]));
  const weights = new Map<string, number>();
  top.forEach((index) => weights.set(period.entities[index], 1 / tailCount));
  bottom.forEach((index) => weights.set(period.entities[index], -1 / tailCount));
  return { weights, grossReturn };
}

export function positionTurnover(previousWeights: Map<string, number>, currentWeights: Map<string, number>) {
  const names = new Set([...previousWeights.keys(), ...currentWeights.keys()]);
  let turnover = 0;
  names.forEach((name) => { turnover += Math.abs((currentWeights.get(name) ?? 0) - (previousWeights.get(name) ?? 0)); });
  return turnover * 0.5;
}

export function driftPosition(period: Period, weights: Map<string, number>) {
  if (weights.size === 0) return new Map<string, number>();
  const grossed = new Map<string, number>();
  for (let index = 0; index < period.observationCount; index += 1) {
    const entity = period.entities[index];
    const weight = weights.get(entity);
    const realizedReturn = period.targetValues[index];
    if (weight === undefined || !Number.isFinite(realizedReturn) || 1 + realizedReturn <= 0) continue;
    grossed.set(entity, weight * (1 + realizedReturn));
  }
  let longTotal = 0;
  let shortTotal = 0;
  grossed.forEach((weight) => {
    if (weight > 0) longTotal += weight;
    else shortTotal -= weight;
  });
  const drifted = new Map<string, number>();
  grossed.forEach((weight, entity) => {
    if (weight > 0 && longTotal > 0) drifted.set(entity, weight / longTotal);
    else if (weight < 0 && shortTotal > 0) drifted.set(entity, weight / shortTotal);
  });
  return drifted;
}

export function portfolioEvidence(
  periods: Period[],
  weighted: Array<{ candidate: Candidate; direction: number; weight: number }>,
  transactionCostBps: number,
  hacLags: number,
) {
  const grossReturns: number[] = [];
  const netReturns: number[] = [];
  const turnovers: number[] = [];
  let previousWeights = new Map<string, number>();
  for (const period of periods) {
    const position = portfolioPosition(period, weighted);
    const turnover = positionTurnover(previousWeights, position.weights);
    const netReturn = position.grossReturn - turnover * transactionCostBps / 10_000;
    grossReturns.push(position.grossReturn);
    netReturns.push(netReturn);
    turnovers.push(turnover);
    previousWeights = driftPosition(period, position.weights);
  }
  const grossInference = oneSidedMeanInference(grossReturns, hacLags);
  const netInference = oneSidedMeanInference(netReturns, hacLags);
  return {
    construction: "equal-weight top-minus-bottom 20%",
    tailShare: 0.2,
    periods: periods.length,
    transactionCostBps,
    meanTurnover: turnovers.length ? average(turnovers) : 0,
    gross: grossInference,
    net: netInference,
  };
}

