/// <reference lib="webworker" />

import { candidateVector, ensembleScores, portfolioPosition, positionTurnover, driftPosition, portfolioEvidence } from "./discovery/portfolio-evidence";
import { candidateValue, alignedHistoricalValue, candidateObservation, candidateSeries, proposalCandidate, generateCandidates, evaluate } from "./discovery/candidate-formulas";
import { average, standardDeviation, neweyWestMeanStandardError, normalCdf, oneSidedMeanInference, binomialPositiveTail, adjustPvaluesHolm, ranks, correlation, pairwiseCorrelation, periodRankIC } from "./discovery/statistics";
import type { InspectRequest, AIProposal, DataFrequency, ResearchConfig, AuditRequest, RunRequest, RequestMessage, Candidate, Period, PeriodBucket, Metrics } from "./discovery/worker-types";

const MAX_FILE_BYTES = 200 * 1024 * 1024;
const MAX_ROWS = 500_000;
const MAX_COLUMNS = 200;
const MAX_FEATURES = 50;
const MAX_ESTIMATED_WORKING_BYTES = 640 * 1024 * 1024;
const MAX_CANDIDATE_OBSERVATIONS = 75_000_000;
const MAX_WALK_FORWARD_CANDIDATE_OBSERVATIONS = 75_000_000;
const MIN_ENTITIES_PER_PERIOD = 5;
const MIN_COMPLETE_ROWS = 100;
const SAMPLE_ROWS = 2_000;

const ctx = self as unknown as DedicatedWorkerGlobalScope;
let headers: string[] = [];
let uploadedFile: File | null = null;
let uploadedFilename = "";
let inspectedRowCount = 0;
let activeJob = 0;
let passedAuditFingerprint = "";

const FREQUENCY_PROFILES: Record<DataFrequency, {
  label: string;
  periodsPerYear: number;
  horizons: number[];
  exploratory: { train: number; selection: number; calibration: number };
  walkForward: { train: number; selection: number; calibration: number; test: number };
}> = {
  daily: { label: "Daily", periodsPerYear: 252, horizons: [1, 5, 21, 63, 252], exploratory: { train: 60, selection: 20, calibration: 20 }, walkForward: { train: 504, selection: 63, calibration: 63, test: 252 } },
  weekly: { label: "Weekly", periodsPerYear: 52, horizons: [1, 4, 13, 26, 52], exploratory: { train: 26, selection: 8, calibration: 8 }, walkForward: { train: 104, selection: 13, calibration: 13, test: 52 } },
  monthly: { label: "Monthly", periodsPerYear: 12, horizons: [1, 3, 6, 12], exploratory: { train: 12, selection: 4, calibration: 4 }, walkForward: { train: 24, selection: 3, calibration: 3, test: 12 } },
  quarterly: { label: "Quarterly", periodsPerYear: 4, horizons: [1, 2, 4, 8], exploratory: { train: 8, selection: 2, calibration: 2 }, walkForward: { train: 8, selection: 2, calibration: 2, test: 4 } },
};

function frequencyProfile(config: ResearchConfig) {
  return FREQUENCY_PROFILES[config.frequency];
}

function send(payload: unknown) {
  ctx.postMessage(payload);
}

function fail(message: string): never {
  throw new Error(message);
}

function ensureActive(job: number) {
  if (job !== activeJob) throw new Error("__CANCELLED__");
}

function formatMegabytes(bytes: number) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function auditFingerprint(config: ResearchConfig) {
  return JSON.stringify({
    entityColumn: config.entityColumn,
    dateColumn: config.dateColumn,
    targetColumn: config.targetColumn,
    availabilityColumn: config.availabilityColumn,
    frequency: config.frequency,
    targetHorizonPeriods: config.targetHorizonPeriods,
    featureColumns: config.featureColumns,
  });
}

async function streamCsv(
  file: File,
  job: number,
  handlers: {
    onHeader: (values: string[]) => void;
    onRow: (values: string[], rowNumber: number) => void;
    onProgress?: (ratio: number) => void;
  },
) {
  const reader = file.stream().getReader();
  const decoder = new TextDecoder("utf-8");
  let parsedHeaders = false;
  let rowNumber = 0;
  let bytesRead = 0;
  let lastProgress = -1;
  let row: string[] = [];
  let field = "";
  let quoted = false;
  let quotePending = false;

  const finishRow = () => {
    row.push(field);
    field = "";
    if (!row.some((value) => value.trim() !== "")) {
      row = [];
      return;
    }
    if (!parsedHeaders) {
      handlers.onHeader(row);
      parsedHeaders = true;
    } else {
      rowNumber += 1;
      if (rowNumber > MAX_ROWS) fail(`The browser workspace supports up to ${MAX_ROWS.toLocaleString()} rows.`);
      handlers.onRow(row, rowNumber);
    }
    row = [];
  };

  const consume = (text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      const character = text[index];
      if (quoted) {
        if (quotePending) {
          if (character === '"') {
            field += '"';
            quotePending = false;
            continue;
          }
          quoted = false;
          quotePending = false;
        } else if (character === '"') {
          quotePending = true;
          continue;
        } else {
          field += character;
          continue;
        }
      }

      if (character === '"') {
        quoted = true;
      } else if (character === ",") {
        row.push(field);
        field = "";
      } else if (character === "\n") {
        finishRow();
      } else if (character !== "\r") {
        field += character;
      }
    }
  };

  try {
    while (true) {
      ensureActive(job);
      const chunk = await reader.read();
      if (chunk.done) break;
      bytesRead += chunk.value.byteLength;
      consume(decoder.decode(chunk.value, { stream: true }));
      const progress = file.size > 0 ? Math.min(1, bytesRead / file.size) : 1;
      const progressPoint = Math.floor(progress * 100);
      if (progressPoint >= lastProgress + 2) {
        lastProgress = progressPoint;
        handlers.onProgress?.(progress);
      }
    }
    consume(decoder.decode());
  } finally {
    reader.releaseLock();
  }

  if (quotePending) {
    quotePending = false;
    quoted = false;
  }
  if (quoted) fail("The CSV contains an unterminated quoted field.");
  if (field.length > 0 || row.length > 0) finishRow();
  if (!parsedHeaders) fail("The CSV must contain a header row.");
  if (rowNumber < 100) fail("At least 100 data rows are required.");
  handlers.onProgress?.(1);
  return rowNumber;
}

function normalizeHeaders(values: string[]) {
  const normalized = values.map((value, index) => value.replace(/^\uFEFF/, "").trim() || `column_${index + 1}`);
  if (normalized.length > MAX_COLUMNS) fail(`The browser workspace supports up to ${MAX_COLUMNS} columns.`);
  if (new Set(normalized).size !== normalized.length) fail("Column names must be unique.");
  return normalized;
}

function normalizeRow(values: string[], columnCount: number) {
  return Array.from({ length: columnCount }, (_, index) => values[index]?.trim() ?? "");
}

function finiteNumber(value: string) {
  if (value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

type RunningStats = { count: number; mean: number; m2: number; min: number; max: number };

function emptyStats(): RunningStats {
  return { count: 0, mean: 0, m2: 0, min: Number.POSITIVE_INFINITY, max: Number.NEGATIVE_INFINITY };
}

function updateStats(stats: RunningStats, value: number) {
  stats.count += 1;
  const delta = value - stats.mean;
  stats.mean += delta / stats.count;
  stats.m2 += delta * (value - stats.mean);
  stats.min = Math.min(stats.min, value);
  stats.max = Math.max(stats.max, value);
}

function finishStats(stats: RunningStats) {
  return {
    count: stats.count,
    mean: stats.count ? stats.mean : 0,
    standardDeviation: stats.count > 1 ? Math.sqrt(stats.m2 / (stats.count - 1)) : 0,
    min: stats.count ? stats.min : 0,
    max: stats.count ? stats.max : 0,
  };
}

function median(values: number[]) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function inferFrequency(sortedDates: number[]): DataFrequency {
  if (sortedDates.length < 2) return "monthly";
  const gaps = sortedDates.slice(1).map((date, index) => (date - sortedDates[index]) / 86_400_000).filter((gap) => gap > 0);
  const typicalGap = median(gaps);
  if (typicalGap <= 4) return "daily";
  if (typicalGap <= 12) return "weekly";
  if (typicalGap <= 60) return "monthly";
  return "quarterly";
}

function isRegularGap(previousTimestamp: number, currentTimestamp: number, frequency: DataFrequency) {
  const days = (currentTimestamp - previousTimestamp) / 86_400_000;
  if (frequency === "daily") return days >= 1 && days <= 4;
  if (frequency === "weekly") return days >= 4 && days <= 10;
  const current = new Date(currentTimestamp);
  const previous = new Date(previousTimestamp);
  const monthGap = (current.getUTCFullYear() - previous.getUTCFullYear()) * 12 + current.getUTCMonth() - previous.getUTCMonth();
  return frequency === "monthly" ? monthGap === 1 : monthGap === 3;
}

function resolveMapping(config: ResearchConfig) {
  const entityIndex = headers.indexOf(config.entityColumn);
  const dateIndex = headers.indexOf(config.dateColumn);
  const targetIndex = headers.indexOf(config.targetColumn);
  const availabilityIndex = config.availabilityColumn ? headers.indexOf(config.availabilityColumn) : -1;
  const featureIndices = config.featureColumns.map((column) => headers.indexOf(column));
  if ([entityIndex, dateIndex, targetIndex, ...featureIndices].some((index) => index < 0)) fail("One or more mapped columns are missing.");
  if (config.availabilityColumn && availabilityIndex < 0) fail("The mapped feature-availability column is missing.");
  if (new Set([config.entityColumn, config.dateColumn, config.targetColumn]).size !== 3) fail("Entity, date, and forward-return columns must be distinct.");
  if (new Set(config.featureColumns).size !== config.featureColumns.length) fail("Candidate feature columns must be unique.");
  if (config.featureColumns.length < 2 || config.featureColumns.length > MAX_FEATURES) fail(`Select between 2 and ${MAX_FEATURES} feature columns.`);
  const reservedColumns = [config.entityColumn, config.dateColumn, config.targetColumn, config.availabilityColumn].filter(Boolean);
  if (config.featureColumns.some((column) => reservedColumns.includes(column))) {
    fail("Entity, date, availability, and forward-return columns cannot be used as candidate features.");
  }
  if (!FREQUENCY_PROFILES[config.frequency]) fail("Choose Daily, Weekly, Monthly, or Quarterly frequency.");
  if (!frequencyProfile(config).horizons.includes(config.targetHorizonPeriods)) fail("Choose a target horizon supported by the selected frequency.");
  return { entityIndex, dateIndex, targetIndex, availabilityIndex, featureIndices };
}

async function inspectDataset(file: File, job: number) {
  if (!file.name.toLowerCase().endsWith(".csv")) fail("Choose a comma-delimited CSV file.");
  if (file.size > MAX_FILE_BYTES) fail(`The browser workspace accepts CSV files up to ${formatMegabytes(MAX_FILE_BYTES)}.`);
  const sample: string[][] = [];
  let parsedHeaders: string[] = [];
  const rowCount = await streamCsv(file, job, {
    onHeader(values) {
      parsedHeaders = normalizeHeaders(values);
    },
    onRow(values) {
      if (sample.length < SAMPLE_ROWS) sample.push(normalizeRow(values, parsedHeaders.length));
    },
    onProgress(ratio) {
      send({ type: "PROGRESS", progress: Math.round(2 + ratio * 18), stage: `Scanning ${formatMegabytes(file.size)} locally` });
    },
  });
  ensureActive(job);

  const numericColumns: string[] = [];
  const dateColumns: string[] = [];
  parsedHeaders.forEach((header, columnIndex) => {
    const populated = sample.map((row) => row[columnIndex]).filter(Boolean);
    if (populated.length === 0) return;
    const numericShare = populated.filter((value) => finiteNumber(value) !== null).length / populated.length;
    const dateShare = populated.filter((value) => Number.isNaN(Number(value)) && Number.isFinite(Date.parse(value))).length / populated.length;
    if (numericShare >= 0.9) numericColumns.push(header);
    if (dateShare >= 0.8 || /(^|_)(date|month|time)(_|$)/i.test(header)) dateColumns.push(header);
  });

  const targetColumn = numericColumns.find((column) => /(forward|future|lead|next).*(return|ret)|(return|ret).*(forward|future|lead|next)/i.test(column))
    ?? numericColumns.find((column) => /return|ret/i.test(column))
    ?? numericColumns[numericColumns.length - 1]
    ?? "";
  const dateColumn = dateColumns[0] ?? parsedHeaders.find((column) => /date|month|time/i.test(column)) ?? "";
  const entityColumn = parsedHeaders.find((column) => /^(permno|gvkey|ticker|asset|asset_id|entity|security|id)$/i.test(column))
    ?? parsedHeaders.find((column) => !numericColumns.includes(column) && column !== dateColumn)
    ?? parsedHeaders[0];
  const availabilityColumn = dateColumns.find((column) => column !== dateColumn && /(avail|point|publish|report|filing|rdq)/i.test(column)) ?? "";
  const suggestedFeatures = numericColumns
    .filter((column) => ![entityColumn, dateColumn, targetColumn, availabilityColumn].includes(column))
    .slice(0, MAX_FEATURES);
  const sampledDates = sample.map((row) => Date.parse(row[parsedHeaders.indexOf(dateColumn)])).filter(Number.isFinite);
  const suggestedFrequency = inferFrequency(Array.from(new Set(sampledDates)).sort((left, right) => left - right));

  headers = parsedHeaders;
  inspectedRowCount = rowCount;
  return {
    filename: file.name,
    fileSizeBytes: file.size,
    rowCount,
    columns: parsedHeaders,
    numericColumns,
    dateColumns,
    suggested: { entityColumn, dateColumn, targetColumn, availabilityColumn, featureColumns: suggestedFeatures, frequency: suggestedFrequency },
  };
}

async function auditDataset(config: ResearchConfig, job: number) {
  if (!uploadedFile) fail("Select a CSV file before auditing the dataset.");
  const { entityIndex, dateIndex, targetIndex, availabilityIndex, featureIndices } = resolveMapping(config);
  const entitySets = new Map<number, Set<string>>();
  const periodCompleteCounts = new Map<number, number>();
  const featureStats = config.featureColumns.map(() => emptyStats());
  const featureMissing = config.featureColumns.map(() => 0);
  const targetStats = emptyStats();
  let invalidEntityRows = 0;
  let invalidDateRows = 0;
  let duplicateKeys = 0;
  let missingTargetRows = 0;
  let rowsWithAnyFeatureMissing = 0;
  let completeRows = 0;
  let outOfOrderRows = 0;
  let previousDate = Number.NEGATIVE_INFINITY;
  let missingAvailabilityRows = 0;
  let futureAvailabilityRows = 0;
  let extremeTargetRows = 0;

  await streamCsv(uploadedFile, job, {
    onHeader(values) {
      const currentHeaders = normalizeHeaders(values);
      if (currentHeaders.length !== headers.length || currentHeaders.some((value, index) => value !== headers[index])) {
        fail("The CSV header changed after inspection. Select the file again.");
      }
    },
    onRow(values) {
      const entity = values[entityIndex]?.trim() ?? "";
      const date = Date.parse(values[dateIndex]?.trim() ?? "");
      if (!entity) invalidEntityRows += 1;
      if (!Number.isFinite(date)) invalidDateRows += 1;
      if (!entity || !Number.isFinite(date)) return;

      if (date < previousDate) outOfOrderRows += 1;
      previousDate = date;
      let entities = entitySets.get(date);
      if (!entities) {
        entities = new Set<string>();
        entitySets.set(date, entities);
      }
      if (entities.has(entity)) duplicateKeys += 1;
      else entities.add(entity);

      const target = finiteNumber(values[targetIndex]?.trim() ?? "");
      if (target === null) missingTargetRows += 1;
      else {
        updateStats(targetStats, target);
        if (Math.abs(target) > 1) extremeTargetRows += 1;
      }
      const rawFeatures = featureIndices.map((index, featureIndex) => {
        const value = finiteNumber(values[index]?.trim() ?? "");
        if (value === null) featureMissing[featureIndex] += 1;
        else updateStats(featureStats[featureIndex], value);
        return value;
      });
      if (rawFeatures.some((value) => value === null)) rowsWithAnyFeatureMissing += 1;
      if (target === null || rawFeatures.some((value) => value === null)) return;

      if (availabilityIndex >= 0) {
        const availability = Date.parse(values[availabilityIndex]?.trim() ?? "");
        if (!Number.isFinite(availability)) {
          missingAvailabilityRows += 1;
          return;
        }
        if (availability > date) {
          futureAvailabilityRows += 1;
          return;
        }
      }
      completeRows += 1;
      periodCompleteCounts.set(date, (periodCompleteCounts.get(date) ?? 0) + 1);
    },
    onProgress(ratio) {
      send({ type: "PROGRESS", progress: Math.round(5 + ratio * 55), stage: "Auditing keys, chronology, coverage, and availability" });
    },
  });
  ensureActive(job);

  const periodEntries = Array.from(periodCompleteCounts.entries()).sort((left, right) => left[0] - right[0]);
  const periodCounts = periodEntries.map((entry) => entry[1]);
  const validPeriods = periodCounts.filter((count) => count >= MIN_ENTITIES_PER_PERIOD).length;
  const profile = frequencyProfile(config);
  const requiredPeriods = profile.exploratory.train + profile.exploratory.selection + profile.exploratory.calibration + 2 * config.targetHorizonPeriods;
  const fullAnnualValidationPeriods = profile.walkForward.train + profile.walkForward.selection + profile.walkForward.calibration + 3 * config.targetHorizonPeriods + profile.walkForward.test;
  const periodDates = periodEntries.map((entry) => entry[0]);
  let irregularDateGaps = 0;
  for (let index = 1; index < periodDates.length; index += 1) {
    if (!isRegularGap(periodDates[index - 1], periodDates[index], config.frequency)) irregularDateGaps += 1;
  }

  const rowDenominator = Math.max(1, inspectedRowCount);
  const completeShare = completeRows / rowDenominator;
  const worstFeatureMissingShare = featureMissing.length ? Math.max(...featureMissing.map((count) => count / rowDenominator)) : 0;
  const checks: Array<{ id: string; label: string; status: "PASS" | "WARN" | "FAIL"; detail: string }> = [];
  checks.push({
    id: "stable-key",
    label: "Entity-date uniqueness",
    status: duplicateKeys > 0 ? "FAIL" : "PASS",
    detail: duplicateKeys > 0 ? `${duplicateKeys.toLocaleString()} duplicate stable keys detected.` : "No duplicate entity-date keys detected.",
  });
  checks.push({
    id: "availability",
    label: "Point-in-time availability",
    status: !config.availabilityColumn ? "WARN" : missingAvailabilityRows > 0 || futureAvailabilityRows > 0 ? "FAIL" : "PASS",
    detail: !config.availabilityColumn
      ? "No availability date was supplied; look-ahead safety cannot be independently verified."
      : missingAvailabilityRows > 0 || futureAvailabilityRows > 0
        ? `${missingAvailabilityRows.toLocaleString()} missing and ${futureAvailabilityRows.toLocaleString()} future availability dates among otherwise complete rows.`
        : "Every complete row was available on or before the observation date.",
  });
  checks.push({
    id: "complete-rows",
    label: "Complete-case coverage",
    status: completeRows < MIN_COMPLETE_ROWS ? "FAIL" : completeShare < 0.7 ? "WARN" : "PASS",
    detail: `${completeRows.toLocaleString()} complete rows (${(completeShare * 100).toFixed(1)}% of the panel). ${MIN_COMPLETE_ROWS} are needed to avoid an almost entirely sparse search.`,
  });
  checks.push({
    id: "period-coverage",
    label: "Purged time coverage",
    status: validPeriods < requiredPeriods ? "FAIL" : "PASS",
    detail: `${validPeriods.toLocaleString()} ${profile.label.toLowerCase()} periods contain at least ${MIN_ENTITIES_PER_PERIOD} complete entities. ${requiredPeriods} permit exploratory purged samples; ${fullAnnualValidationPeriods} permit the first full-year walk-forward block. Shorter histories may discover candidates but cannot earn full validation.`,
  });
  checks.push({
    id: "feature-coverage",
    label: "Feature missingness",
    status: worstFeatureMissingShare > 0.5 ? "FAIL" : worstFeatureMissingShare > 0.3 ? "WARN" : "PASS",
    detail: `Worst selected-feature missing rate is ${(worstFeatureMissingShare * 100).toFixed(1)}%.`,
  });
  checks.push({
    id: "chronology",
    label: "Chronological ordering",
    status: outOfOrderRows > 0 ? "WARN" : "PASS",
    detail: outOfOrderRows > 0 ? `${outOfOrderRows.toLocaleString()} rows move backward in date order; the engine will sort periods internally.` : "Rows are non-decreasing by observation date.",
  });
  checks.push({
    id: "frequency",
    label: `${profile.label} continuity`,
    status: irregularDateGaps > 0 ? "WARN" : "PASS",
    detail: irregularDateGaps > 0 ? `${irregularDateGaps.toLocaleString()} adjacent period gaps are unusual for ${profile.label.toLowerCase()} data. Gaps are warnings, not blockers.` : `Observed spacing is consistent with ${profile.label.toLowerCase()} data.`,
  });
  checks.push({
    id: "target-scale",
    label: "Forward-return scale",
    status: extremeTargetRows / rowDenominator > 0.01 ? "WARN" : "PASS",
    detail: `${extremeTargetRows.toLocaleString()} target values exceed ±100%; declared horizon is ${config.targetHorizonPeriods} ${profile.label.toLowerCase()} period${config.targetHorizonPeriods === 1 ? "" : "s"}.`,
  });

  const blockers = checks.filter((check) => check.status === "FAIL").map((check) => check.detail);
  const warnings = checks.filter((check) => check.status === "WARN").map((check) => check.detail);
  const passed = blockers.length === 0;
  passedAuditFingerprint = passed ? auditFingerprint(config) : "";
  entitySets.clear();
  const result = {
    schemaVersion: "browser-data-audit.v1",
    generatedAt: new Date().toISOString(),
    passed,
    blockers,
    warnings,
    configuration: {
      entityColumn: config.entityColumn,
      dateColumn: config.dateColumn,
      targetColumn: config.targetColumn,
      availabilityColumn: config.availabilityColumn || null,
      frequency: config.frequency,
      targetHorizonPeriods: config.targetHorizonPeriods,
      featureColumns: config.featureColumns,
    },
    summary: {
      rows: inspectedRowCount,
      completeRows,
      invalidEntityRows,
      invalidDateRows,
      duplicateKeys,
      missingTargetRows,
      rowsWithAnyFeatureMissing,
      missingAvailabilityRows,
      futureAvailabilityRows,
      outOfOrderRows,
      extremeTargetRows,
    },
    dateCoverage: {
      start: periodDates.length ? new Date(periodDates[0]).toISOString().slice(0, 10) : null,
      end: periodDates.length ? new Date(periodDates[periodDates.length - 1]).toISOString().slice(0, 10) : null,
      totalPeriods: periodDates.length,
      validPeriods,
      irregularDateGaps,
      entitiesPerPeriod: {
        min: periodCounts.length ? Math.min(...periodCounts) : 0,
        median: median(periodCounts),
        max: periodCounts.length ? Math.max(...periodCounts) : 0,
      },
    },
    targetStats: finishStats(targetStats),
    featureCoverage: config.featureColumns.map((column, index) => ({
      column,
      missingRows: featureMissing[index],
      missingShare: featureMissing[index] / rowDenominator,
      ...finishStats(featureStats[index]),
    })),
    checks,
  };
  send({ type: "AUDIT_RESULT", result });
}

function estimateWorkingBytes(rowCount: number, featureCount: number, periodCount: number) {
  return rowCount * (featureCount * 16 + 112) + periodCount * 4_096;
}

async function preparePeriods(config: ResearchConfig, job: number) {
  if (!uploadedFile) fail("Select a CSV file before running discovery.");
  const { entityIndex, dateIndex, targetIndex, availabilityIndex, featureIndices } = resolveMapping(config);

  const grouped = new Map<number, PeriodBucket>();
  let duplicateKeys = 0;
  let completeRows = 0;
  let skippedRows = 0;
  await streamCsv(uploadedFile, job, {
    onHeader(values) {
      const currentHeaders = normalizeHeaders(values);
      if (currentHeaders.length !== headers.length || currentHeaders.some((value, index) => value !== headers[index])) {
        fail("The CSV header changed after inspection. Select the file again.");
      }
    },
    onRow(values) {
      const entity = values[entityIndex]?.trim() ?? "";
      const date = Date.parse(values[dateIndex]?.trim() ?? "");
      if (!entity || !Number.isFinite(date)) {
        skippedRows += 1;
        return;
      }
      let bucket = grouped.get(date);
      if (!bucket) {
        bucket = {
          entities: new Set<string>(),
          entityValues: [],
          targets: [],
          featureColumns: Array.from({ length: featureIndices.length }, () => []),
        };
        grouped.set(date, bucket);
      }
      if (bucket.entities.has(entity)) {
        duplicateKeys += 1;
        return;
      }
      bucket.entities.add(entity);
      const target = finiteNumber(values[targetIndex]?.trim() ?? "");
      const rawFeatures = featureIndices.map((index) => finiteNumber(values[index]?.trim() ?? ""));
      if (target === null || rawFeatures.some((value) => value === null)) {
        skippedRows += 1;
        return;
      }
      if (availabilityIndex >= 0) {
        const availability = Date.parse(values[availabilityIndex]?.trim() ?? "");
        if (!Number.isFinite(availability)) fail("A complete row is missing its feature-availability date. Re-run the data audit.");
        if (availability > date) fail("A feature-availability date occurs after the observation date. Re-run the data audit.");
      }
      bucket.entityValues.push(entity);
      bucket.targets.push(target);
      rawFeatures.forEach((value, index) => bucket?.featureColumns[index].push(value as number));
      completeRows += 1;
      if (completeRows % 2_000 === 0) {
        const estimated = estimateWorkingBytes(completeRows, featureIndices.length, grouped.size);
        if (estimated > MAX_ESTIMATED_WORKING_BYTES) {
          fail(`The selected columns exceed the ${formatMegabytes(MAX_ESTIMATED_WORKING_BYTES)} browser memory budget. Reduce rows or features.`);
        }
      }
    },
    onProgress(ratio) {
      send({ type: "PROGRESS", progress: Math.round(8 + ratio * 12), stage: "Streaming selected columns with memory protection" });
    },
  });
  ensureActive(job);
  if (duplicateKeys > 0) fail(`The mapped entity-date key contains ${duplicateKeys.toLocaleString()} duplicate rows.`);
  if (completeRows < MIN_COMPLETE_ROWS) fail(`At least ${MIN_COMPLETE_ROWS} complete entity-date observations are required after mapping.`);

  const periods: Period[] = [];
  const sortedBuckets = Array.from(grouped.entries()).sort((left, right) => left[0] - right[0]);
  for (const [date, bucket] of sortedBuckets) {
    if (bucket.targets.length < MIN_ENTITIES_PER_PERIOD) continue;
    for (const values of bucket.featureColumns) {
      const mean = average(values);
      const deviation = standardDeviation(values);
      for (let index = 0; index < values.length; index += 1) {
        values[index] = deviation < 1e-12 ? 0 : Math.max(-5, Math.min(5, (values[index] - mean) / deviation));
      }
    }
    const targetValues = bucket.targets;
    const targetRanks = ranks(targetValues);
    bucket.entities.clear();
    periods.push({
      date,
      entities: bucket.entityValues,
      featureColumns: bucket.featureColumns,
      targetValues,
      targetRanks,
      observationCount: targetRanks.length,
      previousPeriod: null,
      previousEntityIndex: null,
    });
  }
  for (let periodIndex = 1; periodIndex < periods.length; periodIndex += 1) {
    const period = periods[periodIndex];
    const previousPeriod = periods[periodIndex - 1];
    const previousIndexByEntity = new Map(previousPeriod.entities.map((entity, index) => [entity, index]));
    period.previousPeriod = previousPeriod;
    period.previousEntityIndex = Int32Array.from(period.entities.map((entity) => previousIndexByEntity.get(entity) ?? -1));
  }
  grouped.clear();
  const profile = frequencyProfile(config);
  const requiredPeriods = profile.exploratory.train + profile.exploratory.selection + profile.exploratory.calibration + 2 * config.targetHorizonPeriods;
  if (periods.length < requiredPeriods) fail(`At least ${requiredPeriods} valid ${profile.label.toLowerCase()} periods are required to preserve separate Train, Selection, and Calibration samples for this horizon. Full-year walk-forward validation is added only when enough later history exists.`);
  const analysisRows = periods.reduce((sum, period) => sum + period.observationCount, 0);
  return {
    periods,
    completeRows,
    skippedRows,
    analysisRows,
    estimatedWorkingSetMB: estimateWorkingBytes(analysisRows, featureIndices.length, periods.length) / (1024 * 1024),
  };
}

function rollingWalkForwardEvidence(
  periods: Period[],
  candidateDictionary: Candidate[],
  config: ResearchConfig,
  job: number,
) {
  const profile = frequencyProfile(config);
  const trainPeriods = profile.walkForward.train;
  const selectionPeriods = profile.walkForward.selection;
  const calibrationPeriods = profile.walkForward.calibration;
  const testBlockPeriods = profile.walkForward.test;
  const purgePeriods = config.targetHorizonPeriods;
  const firstTestIndex = trainPeriods + selectionPeriods + calibrationPeriods + 3 * purgePeriods;
  const eligiblePeriods = Math.max(0, periods.length - firstTestIndex);
  const eligibleBlocks = Math.floor(eligiblePeriods / testBlockPeriods);
  const excludedLeadingPartialPeriods = eligiblePeriods - eligibleBlocks * testBlockPeriods;
  const firstCompleteBlockStart = periods.length - eligibleBlocks * testBlockPeriods;
  const averageObservationsPerPeriod = periods.reduce((sum, period) => sum + period.observationCount, 0) / Math.max(1, periods.length);
  const estimatedCandidateObservationsPerBlock = Math.max(1, Math.ceil(
    averageObservationsPerPeriod
    * (
      (trainPeriods + selectionPeriods) * candidateDictionary.length
      + (calibrationPeriods + testBlockPeriods) * Math.min(10, candidateDictionary.length)
    ),
  ));
  const maximumEvaluatedBlocks = Math.max(1, Math.floor(
    MAX_WALK_FORWARD_CANDIDATE_OBSERVATIONS / estimatedCandidateObservationsPerBlock,
  ));
  const blockStarts = Array.from({ length: eligibleBlocks }, (_, index) => firstCompleteBlockStart + index * testBlockPeriods);
  const evaluatedBlockStarts = blockStarts.slice(-maximumEvaluatedBlocks);
  const blockResults: Array<{
    block: number;
    testStart: string;
    testEnd: string;
    testPeriods: number;
    calibrationPassed: boolean;
    activeComponents: number;
    meanOosRankIC: number | null;
    positiveOosRankICShare: number;
    meanGrossReturn: number;
    meanTurnover: number;
    meanNetReturn: number;
  }> = [];
  const periodResults: Array<{
    block: number;
    testDate: string;
    calibrationPassed: boolean;
    activeComponents: number;
    oosRankIC: number | null;
    grossReturn: number;
    turnover: number;
    netReturn: number;
  }> = [];
  const oosRankIC: number[] = [];
  const grossReturns: number[] = [];
  const netReturns: number[] = [];
  const turnovers: number[] = [];
  let previousWeights = new Map<string, number>();
  let deployedBlocks = 0;

  for (let evaluatedIndex = 0; evaluatedIndex < evaluatedBlockStarts.length; evaluatedIndex += 1) {
    ensureActive(job);
    const blockStart = evaluatedBlockStarts[evaluatedIndex];
    const blockNumber = eligibleBlocks - evaluatedBlockStarts.length + evaluatedIndex + 1;
    send({
      type: "PROGRESS",
      progress: 92 + Math.round(7 * evaluatedIndex / Math.max(1, evaluatedBlockStarts.length)),
      stage: `Full-year walk-forward block ${evaluatedIndex + 1} of ${evaluatedBlockStarts.length}`,
    });
    const trainStart = blockStart - firstTestIndex;
    const train = periods.slice(trainStart, trainStart + trainPeriods);
    const selectionStart = trainStart + trainPeriods + purgePeriods;
    const selection = periods.slice(selectionStart, selectionStart + selectionPeriods);
    const calibrationStart = selectionStart + selectionPeriods + purgePeriods;
    const calibration = periods.slice(calibrationStart, calibrationStart + calibrationPeriods);
    const testPeriods = periods.slice(blockStart, blockStart + testBlockPeriods);

    const trainMinimumPeriods = Math.max(6, Math.ceil(train.length * 0.8));
    const trainScreened = candidateDictionary.map((candidate) => {
      const trainMetrics = evaluate(candidate, train);
      const score = trainMetrics.absMeanRankIC * (0.5 + trainMetrics.hitRate) * Math.sqrt(trainMetrics.validPeriods) / candidate.complexity;
      return { candidate, trainMetrics, score };
    });
    const trainQualified = trainScreened.filter((item) => (
      item.trainMetrics.validPeriods >= trainMinimumPeriods && item.trainMetrics.absMeanRankIC >= 0.002
    ));
    const trainPool = (trainQualified.length >= 10
      ? trainQualified
      : trainScreened.filter((item) => item.trainMetrics.validPeriods >= trainMinimumPeriods))
      .sort((left, right) => right.score - left.score)
      .slice(0, 60);
    const blockCandidates: typeof trainPool = [];
    const blockVectors: number[][] = [];
    for (const item of trainPool) {
      const vector = candidateVector(item.candidate, train);
      if (blockVectors.some((keptVector) => Math.abs(pairwiseCorrelation(vector, keptVector)) >= config.correlationThreshold)) continue;
      blockCandidates.push(item);
      blockVectors.push(vector);
      if (blockCandidates.length >= 30) break;
    }
    if (blockCandidates.length < 2) {
      for (const item of trainPool) {
        if (blockCandidates.some((kept) => kept.candidate.id === item.candidate.id)) continue;
        blockCandidates.push(item);
        if (blockCandidates.length >= 2) break;
      }
    }
    const selectionDraft = blockCandidates.map(({ candidate, trainMetrics }) => {
      const direction = trainMetrics.meanRankIC >= 0 ? 1 : -1;
      const selectionMetrics = evaluate(candidate, selection);
      return {
        candidate,
        direction,
        selectionEdge: direction * selectionMetrics.meanRankIC,
      };
    }).sort((left, right) => right.selectionEdge - left.selectionEdge);
    let active = selectionDraft.filter((item) => item.selectionEdge > 0.001).slice(0, 10);
    if (active.length < 2) active = selectionDraft.slice(0, Math.min(5, selectionDraft.length));
    const rawWeights = active.map((item) => Math.max(0.0001, item.selectionEdge));
    const weightTotal = rawWeights.reduce((sum, value) => sum + value, 0);
    const weighted = active.map((item, index) => ({ ...item, weight: rawWeights[index] / weightTotal }));
    const calibrationIC = calibration.map((period) => periodRankIC(ensembleScores(period, weighted), period)).filter(Number.isFinite);
    const calibrationPassed = calibrationIC.length === calibrationPeriods
      && average(calibrationIC) >= 0.01
      && calibrationIC.filter((value) => value > 0).length / calibrationIC.length >= 0.55;

    const deployed = calibrationPassed ? weighted : [];
    if (calibrationPassed) deployedBlocks += 1;
    const blockRankIC: number[] = [];
    const blockGrossReturns: number[] = [];
    const blockNetReturns: number[] = [];
    const blockTurnovers: number[] = [];
    for (const testPeriod of testPeriods) {
      const scores = calibrationPassed ? ensembleScores(testPeriod, weighted) : [];
      const rankIC = calibrationPassed ? periodRankIC(scores, testPeriod) : Number.NaN;
      const position = portfolioPosition(testPeriod, deployed);
      const turnover = positionTurnover(previousWeights, position.weights);
      const netReturn = position.grossReturn - turnover * config.transactionCostBps / 10_000;
      if (Number.isFinite(rankIC)) {
        oosRankIC.push(rankIC);
        blockRankIC.push(rankIC);
      }
      grossReturns.push(position.grossReturn);
      netReturns.push(netReturn);
      turnovers.push(turnover);
      blockGrossReturns.push(position.grossReturn);
      blockNetReturns.push(netReturn);
      blockTurnovers.push(turnover);
      periodResults.push({
        block: blockNumber,
        testDate: new Date(testPeriod.date).toISOString().slice(0, 10),
        calibrationPassed,
        activeComponents: calibrationPassed ? weighted.length : 0,
        oosRankIC: Number.isFinite(rankIC) ? rankIC : null,
        grossReturn: position.grossReturn,
        turnover,
        netReturn,
      });
      previousWeights = driftPosition(testPeriod, position.weights);
    }
    blockResults.push({
      block: blockNumber,
      testStart: new Date(testPeriods[0].date).toISOString().slice(0, 10),
      testEnd: new Date(testPeriods[testPeriods.length - 1].date).toISOString().slice(0, 10),
      testPeriods: testPeriods.length,
      calibrationPassed,
      activeComponents: calibrationPassed ? weighted.length : 0,
      meanOosRankIC: blockRankIC.length ? average(blockRankIC) : null,
      positiveOosRankICShare: blockRankIC.length ? blockRankIC.filter((value) => value > 0).length / blockRankIC.length : 0,
      meanGrossReturn: average(blockGrossReturns),
      meanTurnover: average(blockTurnovers),
      meanNetReturn: average(blockNetReturns),
    });
  }

  const hacLags = Math.max(0, config.targetHorizonPeriods - 1);
  return {
    protocol: `frequency-aware-${config.frequency}-full-year-refit`,
    frequency: config.frequency,
    periodsPerYear: profile.periodsPerYear,
    candidateDictionarySize: candidateDictionary.length,
    trainPeriods,
    selectionPeriods,
    calibrationPeriods,
    testBlockPeriods,
    refitIntervalPeriods: testBlockPeriods,
    purgePeriodsPerBoundary: purgePeriods,
    eligiblePeriods,
    excludedLeadingPartialPeriods,
    eligibleBlocks,
    evaluatedBlocks: blockResults.length,
    evaluatedPeriods: periodResults.length,
    maximumEvaluatedBlocks,
    truncated: eligibleBlocks > maximumEvaluatedBlocks,
    estimatedCandidateObservationsPerBlock,
    estimatedRollingCandidateObservations: estimatedCandidateObservationsPerBlock * blockResults.length,
    candidateObservationBudget: MAX_WALK_FORWARD_CANDIDATE_OBSERVATIONS,
    deployedBlocks,
    cashBlocks: blockResults.length - deployedBlocks,
    meanTurnover: turnovers.length ? average(turnovers) : 0,
    oosRankIC: oneSidedMeanInference(oosRankIC, hacLags),
    positiveOosRankICShare: oosRankIC.length ? oosRankIC.filter((value) => value > 0).length / oosRankIC.length : 0,
    gross: oneSidedMeanInference(grossReturns, hacLags),
    net: oneSidedMeanInference(netReturns, hacLags),
    blocks: blockResults,
    periods: periodResults,
  };
}

async function runDiscovery(config: ResearchConfig, job: number) {
  if (passedAuditFingerprint !== auditFingerprint(config)) fail("Audit the current data mapping before running discovery.");
  if (![100, 250, 500].includes(config.candidateBudget)) fail("Candidate budget must be 100, 250, or 500.");
  if (![0.7, 0.8, 0.9].includes(config.correlationThreshold)) fail("Correlation threshold must be 0.7, 0.8, or 0.9.");
  if (![0, 10, 25, 50].includes(config.transactionCostBps)) fail("Transaction cost must be 0, 10, 25, or 50 basis points.");
  send({ type: "PROGRESS", progress: 6, stage: "Validating the panel" });
  const { periods, completeRows, skippedRows, analysisRows, estimatedWorkingSetMB } = await preparePeriods(config, job);
  const profile = frequencyProfile(config);
  const purgePeriods = config.targetHorizonPeriods;
  const exploratory = profile.exploratory;
  const trainBoundary = Math.min(
    Math.max(exploratory.train + purgePeriods, Math.floor(periods.length * 0.6)),
    periods.length - exploratory.selection - exploratory.calibration - purgePeriods,
  );
  const selectionBoundary = Math.min(
    Math.max(trainBoundary + exploratory.selection + purgePeriods, Math.floor(periods.length * 0.8)),
    periods.length - exploratory.calibration,
  );
  const train = periods.slice(0, trainBoundary - purgePeriods);
  const selection = periods.slice(trainBoundary, selectionBoundary - purgePeriods);
  const calibration = periods.slice(selectionBoundary);
  if (train.length < exploratory.train || selection.length < exploratory.selection || calibration.length < exploratory.calibration) {
    fail("The horizon-aware purge does not leave enough Train, Selection, and Calibration periods.");
  }

  const candidates = generateCandidates(config.featureColumns, config.candidateBudget, config.aiProposals ?? []);
  const candidateObservations = analysisRows * candidates.length;
  if (candidateObservations > MAX_CANDIDATE_OBSERVATIONS) {
    fail(`This run would evaluate ${(candidateObservations / 1_000_000).toFixed(0)} million candidate observations. Reduce the candidate budget or the panel size.`);
  }
  send({ type: "PROGRESS", progress: 22, stage: `Generated ${candidates.length} deterministic candidates` });
  const evaluated = candidates.map((candidate, index) => {
    ensureActive(job);
    if (index % 10 === 0) send({ type: "PROGRESS", progress: 22 + Math.round(33 * index / candidates.length), stage: "Screening candidates in Train" });
    const metrics = evaluate(candidate, train);
    return { candidate, metrics, score: metrics.absMeanRankIC * (0.5 + metrics.stability) * Math.sqrt(metrics.validPeriods) / candidate.complexity };
  });
  const minimumPeriods = Math.max(6, Math.ceil(train.length * 0.8));
  const qualified = evaluated.filter((item) => item.metrics.validPeriods >= minimumPeriods && item.metrics.absMeanRankIC >= 0.002);
  const screeningPool = (qualified.length >= 10 ? qualified : evaluated.filter((item) => item.metrics.validPeriods >= minimumPeriods))
    .sort((left, right) => right.score - left.score)
    .slice(0, 60);
  if (screeningPool.length < 2) fail("No candidates have enough valid Train-period observations.");

  send({ type: "PROGRESS", progress: 60, stage: "Pruning correlated candidate exposures" });
  const kept: typeof screeningPool = [];
  const keptVectors: number[][] = [];
  let redundantCandidates = 0;
  for (const item of screeningPool) {
    ensureActive(job);
    const vector = candidateVector(item.candidate, train);
    const redundant = keptVectors.some((keptVector) => Math.abs(pairwiseCorrelation(vector, keptVector)) >= config.correlationThreshold);
    if (!redundant) {
      kept.push(item);
      keptVectors.push(vector);
    } else redundantCandidates += 1;
    if (kept.length >= 30) break;
  }
  if (kept.length < 2) fail("Correlation pruning left fewer than two distinct candidates.");

  send({ type: "PROGRESS", progress: 73, stage: "Running Selection HAC and Holm correction" });
  const selectionDraft = kept.map((item) => {
    const direction = item.metrics.meanRankIC >= 0 ? 1 : -1;
    const selectionMetrics = evaluate(item.candidate, selection);
    const directionalSeries = selectionMetrics.icSeries.map((value) => direction * value);
    const meanInference = oneSidedMeanInference(directionalSeries, Math.max(0, config.targetHorizonPeriods - 1));
    const directionalPvalue = binomialPositiveTail(directionalSeries.filter((value) => value > 0).length, directionalSeries.length);
    return { ...item, direction, selectionMetrics, selectionEdge: meanInference.mean, meanInference, directionalPvalue };
  });
  const selectionFamilySize = 2 * selectionDraft.length;
  const selectionAdjusted = adjustPvaluesHolm([
    ...selectionDraft.map((item) => item.meanInference.pValue),
    ...selectionDraft.map((item) => item.directionalPvalue),
  ]);
  const selectionEvaluated = selectionDraft.map((item, index) => ({
    ...item,
    adjustedMeanPvalue: selectionAdjusted[index],
    adjustedDirectionalPvalue: selectionAdjusted[index + selectionDraft.length],
  })).sort((left, right) => right.selectionEdge - left.selectionEdge);
  let active = selectionEvaluated.filter((item) => item.selectionEdge > 0.001).slice(0, 10);
  if (active.length < 2) active = selectionEvaluated.slice(0, Math.min(5, selectionEvaluated.length));
  const rawWeights = active.map((item) => Math.max(0.0001, item.selectionEdge));
  const weightTotal = rawWeights.reduce((sum, value) => sum + value, 0);
  const weighted = active.map((item, index) => ({ ...item, weight: rawWeights[index] / weightTotal }));

  send({ type: "PROGRESS", progress: 86, stage: "Running purged Calibration inference and cost test" });
  const calibrationIC = calibration.map((period) => {
    const score = ensembleScores(period, weighted);
    return periodRankIC(score, period);
  }).filter(Number.isFinite);
  const hacLags = Math.max(0, config.targetHorizonPeriods - 1);
  const calibrationMeanInference = oneSidedMeanInference(calibrationIC, hacLags);
  const calibrationDirectionalPvalue = binomialPositiveTail(calibrationIC.filter((value) => value > 0).length, calibrationIC.length);
  const calibrationAdjusted = adjustPvaluesHolm([calibrationMeanInference.pValue, calibrationDirectionalPvalue]);
  const calibrationMeanRankIC = calibrationMeanInference.mean;
  const calibrationDeviation = standardDeviation(calibrationIC);
  const calibrationHitRate = calibrationIC.length ? calibrationIC.filter((value) => value > 0).length / calibrationIC.length : 0;
  const calibrationPassed = calibrationIC.length >= Math.max(3, Math.ceil(calibration.length * 0.7))
    && calibrationMeanRankIC >= 0.01
    && calibrationHitRate >= 0.55;
  const portfolio = portfolioEvidence(calibration, weighted, config.transactionCostBps, hacLags);
  send({ type: "PROGRESS", progress: 92, stage: `Running full-year ${profile.label.toLowerCase()} frozen-model walk-forward blocks` });
  const walkForward = rollingWalkForwardEvidence(periods, candidates, config, job);
  const validationGates = [
    {
      id: "calibration-signal",
      label: "Calibration signal",
      passed: calibrationPassed,
      detail: `Mean RankIC ${calibrationMeanRankIC.toFixed(4)} and ${(calibrationHitRate * 100).toFixed(1)}% positive periods; requires RankIC ≥ 0.0100 and positive share ≥ 55%.`,
    },
    {
      id: "multiplicity",
      label: "Multiplicity-adjusted inference",
      passed: calibrationAdjusted.every((value) => value <= 0.1),
      detail: `Worst joint Holm-adjusted p-value ${Math.max(...calibrationAdjusted).toFixed(3)}; requires ≤ 0.100.`,
    },
    {
      id: "calibration-net-return",
      label: "Calibration net return",
      passed: portfolio.net.mean > 0,
      detail: `Cost-adjusted top-minus-bottom mean ${(portfolio.net.mean * 100).toFixed(2)}%; requires a positive value.`,
    },
    {
      id: "calibration-net-inference",
      label: "Calibration net-return inference",
      passed: portfolio.net.pValue <= 0.1,
      detail: `One-sided HAC p-value ${portfolio.net.pValue.toFixed(3)}; requires ≤ 0.100.`,
    },
    {
      id: "walk-forward-coverage",
      label: "Walk-forward coverage",
      passed: walkForward.evaluatedBlocks >= 3,
      detail: `${walkForward.evaluatedBlocks} complete full-year out-of-sample blocks and ${walkForward.evaluatedPeriods} ${frequencyProfile(config).label.toLowerCase()} returns evaluated; requires at least 3 full-year blocks.`,
    },
    {
      id: "walk-forward-deployment",
      label: "Walk-forward deployment",
      passed: walkForward.deployedBlocks >= 1,
      detail: `${walkForward.deployedBlocks} full-year blocks passed Calibration and deployed; requires at least 1.`,
    },
    {
      id: "walk-forward-net-return",
      label: "Walk-forward net return",
      passed: walkForward.net.mean > 0,
      detail: `Mean net out-of-sample spread ${(walkForward.net.mean * 100).toFixed(2)}%; requires a positive value including full-year cash blocks.`,
    },
  ];
  const professionalValidationPassed = validationGates.every((gate) => gate.passed);
  const walkForwardEvidence = (
    (walkForward.oosRankIC.mean > 0 && walkForward.oosRankIC.pValue <= 0.1)
    || (walkForward.net.mean > 0 && walkForward.net.pValue <= 0.1)
  );
  const evidenceTier = professionalValidationPassed
    ? "validated"
    : walkForward.deployedBlocks > 0 && walkForwardEvidence
      ? "regime-dependent"
      : calibrationPassed || selectionEvaluated.some((item) => item.adjustedMeanPvalue <= 0.1 && item.adjustedDirectionalPvalue <= 0.1)
        ? "candidate"
        : "no-reliable-signal";
  const assessment = evidenceTier === "validated"
    ? {
        tier: evidenceTier,
        label: "VALIDATED FACTOR",
        headline: "A candidate survived every configured research check.",
        detail: "The frozen ensemble passed Calibration, trading-cost, and frequency-aware full-year walk-forward gates. An external untouched holdout is still required before any performance claim.",
      }
    : evidenceTier === "regime-dependent"
      ? {
          tier: evidenceTier,
          label: "REGIME-DEPENDENT CANDIDATE",
          headline: "The engine found signal, but it did not persist across the full history.",
          detail: `${walkForward.deployedBlocks} of ${walkForward.evaluatedBlocks} full-year blocks deployed after Calibration. Inspect the block ledger and timeline before deciding whether the candidate is economically meaningful or decayed.`,
        }
      : evidenceTier === "candidate"
        ? {
            tier: evidenceTier,
            label: "CANDIDATE FOUND · VALIDATION INCOMPLETE",
            headline: "A research candidate was found, but the evidence is not yet strong enough for validation.",
            detail: "Use the failed gates to identify whether multiplicity, costs, or out-of-sample stability is the limiting evidence. Do not treat this tier as a trading result.",
          }
        : {
            tier: evidenceTier,
            label: "NO RELIABLE SIGNAL",
            headline: "The search produced formulas, but none earned reliable out-of-sample evidence.",
            detail: "The component table remains an audit trail of what was tested; it is not a factor recommendation. Add economically distinct features or more history instead of relaxing gates after seeing this result.",
          };

  const result = {
    schemaVersion: "browser-factor-discovery.v10",
    generatedAt: new Date().toISOString(),
    source: {
      filename: uploadedFilename,
      fileSizeBytes: uploadedFile?.size ?? 0,
      rowCount: inspectedRowCount,
      completeRows,
      skippedRows,
      dataLeftBrowser: false,
    },
    mapping: config,
    periods: {
      total: periods.length,
      train: train.length,
      selection: selection.length,
      calibration: calibration.length,
      purged: 2 * purgePeriods,
    },
    resourceUse: {
      parser: "streaming-csv",
      selectedColumnsOnly: true,
      estimatedWorkingSetMB,
      candidateObservations,
      estimatedRollingCandidateObservations: walkForward.estimatedRollingCandidateObservations,
      totalEstimatedCandidateObservations: candidateObservations + walkForward.estimatedRollingCandidateObservations,
      limits: {
        fileBytes: MAX_FILE_BYTES,
        rows: MAX_ROWS,
        features: MAX_FEATURES,
        estimatedWorkingBytes: MAX_ESTIMATED_WORKING_BYTES,
        candidateObservations: MAX_CANDIDATE_OBSERVATIONS,
        rollingCandidateObservations: MAX_WALK_FORWARD_CANDIDATE_OBSERVATIONS,
      },
    },
    summary: {
      generatedCandidates: candidates.length,
      trainQualified: qualified.length,
      correlationPruned: kept.length,
      activeComponents: weighted.length,
      calibrationPassed,
      professionalValidationPassed,
      calibrationMeanRankIC,
      calibrationICIR: calibrationDeviation > 1e-12 ? calibrationMeanRankIC / calibrationDeviation : 0,
      calibrationHitRate,
    },
    screeningDiagnostics: {
      generated: evaluated.length,
      insufficientHistory: evaluated.filter((item) => item.metrics.validPeriods < minimumPeriods).length,
      weakTrainSignal: evaluated.filter((item) => item.metrics.validPeriods >= minimumPeriods && item.metrics.absMeanRankIC < 0.002).length,
      passedTrainScreen: qualified.length,
      trainShortlist: screeningPool.length,
      redundantCandidates,
      distinctCandidates: kept.length,
      nonPositiveSelectionEdge: selectionEvaluated.filter((item) => item.selectionEdge <= 0.001).length,
      multiplicityFailed: selectionEvaluated.filter((item) => item.adjustedMeanPvalue > 0.1 || item.adjustedDirectionalPvalue > 0.1).length,
      explanation: "Counts describe statistical screening outcomes, not economic verdicts. A rejected transformation may be redundant, too sparse, too weak in Train, unstable in Selection, or unable to survive multiple-testing correction.",
    },
    assessment,
    validation: {
      protocol: "frequency-aware-purged-hac-holm-cost-full-year-walk-forward-v4",
      purge: {
        periodsPerBoundary: purgePeriods,
        totalPurgedPeriods: 2 * purgePeriods,
        reason: `Prevent ${config.targetHorizonPeriods}-${frequencyProfile(config).label.toLowerCase()}-period forward-return labels from crossing stage boundaries.`,
      },
      multipleTesting: {
        method: "Holm-Bonferroni joint family",
        selectionFamilySize,
        selectionCandidatesPassing10Pct: selectionEvaluated.filter((item) => item.adjustedMeanPvalue <= 0.1 && item.adjustedDirectionalPvalue <= 0.1).length,
        calibrationFamilySize: 2,
      },
      calibrationInference: {
        meanRankIC: calibrationMeanInference,
        directionalPvalue: calibrationDirectionalPvalue,
        adjustedMeanPvalue: calibrationAdjusted[0],
        adjustedDirectionalPvalue: calibrationAdjusted[1],
      },
      portfolio,
      walkForward,
      gates: validationGates,
      passed: professionalValidationPassed,
    },
    components: weighted.map((item, index) => ({
      rank: index + 1,
      expression: item.candidate.expression,
      operation: item.candidate.operation,
      family: item.candidate.family,
      complexity: item.candidate.complexity,
      lookbackPeriods: item.candidate.lookbackPeriods,
      source: item.candidate.source,
      direction: item.direction,
      weight: item.weight,
      train: {
        meanRankIC: item.metrics.meanRankIC,
        absMeanRankIC: item.metrics.absMeanRankIC,
        icir: item.metrics.icir,
        stability: item.metrics.stability,
        validPeriods: item.metrics.validPeriods,
      },
      selection: {
        meanRankIC: item.selectionMetrics.meanRankIC,
        icir: item.selectionMetrics.icir,
        validPeriods: item.selectionMetrics.validPeriods,
        hacStandardError: item.meanInference.standardError,
        rawMeanPvalue: item.meanInference.pValue,
        rawDirectionalPvalue: item.directionalPvalue,
        adjustedMeanPvalue: item.adjustedMeanPvalue,
        adjustedDirectionalPvalue: item.adjustedDirectionalPvalue,
      },
    })),
    interpretation: {
      gate: "Purged Calibration inference, joint Holm adjustment, cost-adjusted portfolios, and frequency-aware full-year walk-forward evidence",
      formalHoldoutIncluded: false,
      investmentAdvice: false,
    },
  };
  send({ type: "PROGRESS", progress: 100, stage: "Discovery complete" });
  send({ type: "RESULT", result });
}

async function handleMessage(message: RequestMessage, job: number) {
  try {
    if (message.type === "INSPECT") {
      uploadedFile = message.file;
      uploadedFilename = message.file.name;
      headers = [];
      inspectedRowCount = 0;
      passedAuditFingerprint = "";
      const inspection = await inspectDataset(message.file, job);
      ensureActive(job);
      send({ type: "INSPECTION", inspection });
      return;
    }
    if (!uploadedFile || headers.length === 0) fail("Select a CSV file before running discovery.");
    if (message.type === "AUDIT") {
      passedAuditFingerprint = "";
      await auditDataset(message.config, job);
      return;
    }
    await runDiscovery(message.config, job);
  } catch (error) {
    if (job !== activeJob || (error instanceof Error && error.message === "__CANCELLED__")) return;
    send({ type: "ERROR", message: error instanceof Error ? error.message : "The discovery job failed." });
  }
}

ctx.onmessage = (event: MessageEvent<RequestMessage>) => {
  const job = activeJob + 1;
  activeJob = job;
  void handleMessage(event.data, job);
};
