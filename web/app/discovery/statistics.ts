import type { Period } from "./worker-types";

export function average(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function standardDeviation(values: number[]) {
  if (values.length < 2) return 0;
  const mean = average(values);
  return Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1));
}

export function neweyWestMeanStandardError(values: number[], maxLag: number) {
  const sample = values.filter(Number.isFinite);
  if (sample.length < 2) return Number.NaN;
  const mean = average(sample);
  const deviations = sample.map((value) => value - mean);
  const sampleDeviation = standardDeviation(sample);
  const iidStandardError = sampleDeviation / Math.sqrt(sample.length);
  let longRunVariance = deviations.reduce((sum, value) => sum + value * value, 0) / sample.length;
  const lagLimit = Math.min(Math.max(0, maxLag), sample.length - 1);
  for (let lag = 1; lag <= lagLimit; lag += 1) {
    let covariance = 0;
    for (let index = lag; index < deviations.length; index += 1) covariance += deviations[index] * deviations[index - lag];
    covariance /= sample.length;
    longRunVariance += 2 * (1 - lag / (lagLimit + 1)) * covariance;
  }
  const hacStandardError = Math.sqrt(Math.max(0, longRunVariance) / sample.length);
  return Math.max(iidStandardError, hacStandardError);
}

export function normalCdf(value: number) {
  const sign = value < 0 ? -1 : 1;
  const absolute = Math.abs(value) / Math.sqrt(2);
  const t = 1 / (1 + 0.3275911 * absolute);
  const erf = sign * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-absolute * absolute));
  return 0.5 * (1 + erf);
}

export function oneSidedMeanInference(values: number[], maxLag: number) {
  const sample = values.filter(Number.isFinite);
  const mean = sample.length ? average(sample) : 0;
  const standardError = neweyWestMeanStandardError(sample, maxLag);
  const tStatistic = Number.isFinite(standardError) && standardError > 1e-12
    ? mean / standardError
    : mean > 0 ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
  const pValue = Number.isFinite(tStatistic) ? Math.max(0, Math.min(1, 1 - normalCdf(tStatistic))) : tStatistic > 0 ? 0 : 1;
  return { mean, standardError, tStatistic, pValue, observations: sample.length, hacLags: Math.min(maxLag, Math.max(0, sample.length - 1)) };
}

export function binomialPositiveTail(successes: number, trials: number) {
  if (trials <= 0) return 1;
  if (trials > 500) {
    const standardDeviation = Math.sqrt(trials * 0.25);
    const zStatistic = (successes - 0.5 - trials * 0.5) / standardDeviation;
    return Math.max(0, Math.min(1, 1 - normalCdf(zStatistic)));
  }
  let probability = 2 ** (-trials);
  let tail = successes <= 0 ? probability : 0;
  for (let count = 0; count < trials; count += 1) {
    probability *= (trials - count) / (count + 1);
    if (count + 1 >= successes) tail += probability;
  }
  return Math.max(0, Math.min(1, tail));
}

export function adjustPvaluesHolm(pvalues: number[]) {
  const sanitized = pvalues.map((value) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1);
  const order = sanitized.map((value, index) => ({ value, index })).sort((left, right) => left.value - right.value);
  const adjusted = new Array<number>(sanitized.length).fill(1);
  let runningMaximum = 0;
  order.forEach((item, rank) => {
    runningMaximum = Math.max(runningMaximum, (order.length - rank) * item.value);
    adjusted[item.index] = Math.min(1, runningMaximum);
  });
  return adjusted;
}

export function ranks(values: number[]) {
  const order = values.map((value, index) => ({ value, index })).sort((a, b) => a.value - b.value);
  const result = new Array<number>(values.length);
  let cursor = 0;
  while (cursor < order.length) {
    let end = cursor + 1;
    while (end < order.length && order[end].value === order[cursor].value) end += 1;
    const rank = (cursor + end - 1) / 2 + 1;
    for (let index = cursor; index < end; index += 1) result[order[index].index] = rank;
    cursor = end;
  }
  return result;
}

export function correlation(left: number[], right: number[]) {
  if (left.length !== right.length || left.length < 5) return Number.NaN;
  const leftMean = average(left);
  const rightMean = average(right);
  let numerator = 0;
  let leftVariance = 0;
  let rightVariance = 0;
  for (let index = 0; index < left.length; index += 1) {
    const leftDelta = left[index] - leftMean;
    const rightDelta = right[index] - rightMean;
    numerator += leftDelta * rightDelta;
    leftVariance += leftDelta * leftDelta;
    rightVariance += rightDelta * rightDelta;
  }
  const denominator = Math.sqrt(leftVariance * rightVariance);
  return denominator > 1e-12 ? numerator / denominator : Number.NaN;
}

export function pairwiseCorrelation(left: number[], right: number[]) {
  if (left.length !== right.length) return Number.NaN;
  const valid = left.map((value, index) => Number.isFinite(value) && Number.isFinite(right[index]) ? index : -1).filter((index) => index >= 0);
  if (valid.length < 5) return Number.NaN;
  return correlation(valid.map((index) => left[index]), valid.map((index) => right[index]));
}

export function periodRankIC(scores: number[], period: Period) {
  const valid = scores.map((value, index) => Number.isFinite(value) ? index : -1).filter((index) => index >= 0);
  if (valid.length < 5) return Number.NaN;
  return correlation(ranks(valid.map((index) => scores[index])), valid.map((index) => period.targetRanks[index]));
}

