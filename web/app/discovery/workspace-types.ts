export type Inspection = {
  filename: string;
  fileSizeBytes: number;
  rowCount: number;
  columns: string[];
  numericColumns: string[];
  dateColumns: string[];
  suggested: {
    entityColumn: string;
    dateColumn: string;
    targetColumn: string;
    availabilityColumn: string;
    featureColumns: string[];
    frequency: DataFrequency;
  };
};

export type DataFrequency = "daily" | "weekly" | "monthly" | "quarterly";
export const FREQUENCY_OPTIONS: Record<DataFrequency, { label: string; periodsPerYear: number; horizons: number[] }> = {
  daily: { label: "Daily", periodsPerYear: 252, horizons: [1, 5, 21, 63, 252] },
  weekly: { label: "Weekly", periodsPerYear: 52, horizons: [1, 4, 13, 26, 52] },
  monthly: { label: "Monthly", periodsPerYear: 12, horizons: [1, 3, 6, 12] },
  quarterly: { label: "Quarterly", periodsPerYear: 4, horizons: [1, 2, 4, 8] },
};

export type AuditResult = {
  passed: boolean;
  blockers: string[];
  warnings: string[];
  configuration: {
    entityColumn: string;
    dateColumn: string;
    targetColumn: string;
    availabilityColumn: string | null;
    frequency: DataFrequency;
    targetHorizonPeriods: number;
    featureColumns: string[];
  };
  summary: {
    rows: number;
    completeRows: number;
    invalidEntityRows: number;
    invalidDateRows: number;
    duplicateKeys: number;
    missingTargetRows: number;
    rowsWithAnyFeatureMissing: number;
    missingAvailabilityRows: number;
    futureAvailabilityRows: number;
    outOfOrderRows: number;
    extremeTargetRows: number;
  };
  dateCoverage: {
    start: string | null;
    end: string | null;
    totalPeriods: number;
    validPeriods: number;
    irregularDateGaps: number;
    entitiesPerPeriod: { min: number; median: number; max: number };
  };
  featureCoverage: Array<{ column: string; missingRows: number; missingShare: number }>;
  checks: Array<{ id: string; label: string; status: "PASS" | "WARN" | "FAIL"; detail: string }>;
};

export type DiscoveryResult = {
  schemaVersion: string;
  generatedAt: string;
  source: { filename: string; fileSizeBytes: number; rowCount: number; completeRows: number; skippedRows: number; dataLeftBrowser: false };
  mapping: {
    entityColumn: string;
    dateColumn: string;
    targetColumn: string;
    availabilityColumn: string;
    frequency: DataFrequency;
    targetHorizonPeriods: number;
    featureColumns: string[];
    candidateBudget: number;
    correlationThreshold: number;
    transactionCostBps: number;
  };
  periods: { total: number; train: number; selection: number; calibration: number; purged: number };
  resourceUse: {
    parser: "streaming-csv";
    selectedColumnsOnly: true;
    estimatedWorkingSetMB: number;
    candidateObservations: number;
    estimatedRollingCandidateObservations: number;
    totalEstimatedCandidateObservations: number;
  };
  summary: {
    generatedCandidates: number;
    trainQualified: number;
    correlationPruned: number;
    activeComponents: number;
    calibrationPassed: boolean;
    professionalValidationPassed: boolean;
    calibrationMeanRankIC: number;
    calibrationICIR: number;
    calibrationHitRate: number;
  };
  screeningDiagnostics: {
    generated: number;
    insufficientHistory: number;
    weakTrainSignal: number;
    passedTrainScreen: number;
    trainShortlist: number;
    redundantCandidates: number;
    distinctCandidates: number;
    nonPositiveSelectionEdge: number;
    multiplicityFailed: number;
    explanation: string;
  };
  assessment: {
    tier: "validated" | "regime-dependent" | "candidate" | "no-reliable-signal";
    label: string;
    headline: string;
    detail: string;
  };
  components: Array<{
    rank: number;
    expression: string;
    operation: string;
    family: "primitive" | "nonlinear" | "temporal" | "interaction";
    complexity: number;
    lookbackPeriods: number;
    source: "deterministic" | "ai-proposed";
    direction: number;
    weight: number;
    train: { meanRankIC: number; absMeanRankIC: number; icir: number; stability: number; validPeriods: number };
    selection: {
      meanRankIC: number;
      icir: number;
      validPeriods: number;
      hacStandardError: number;
      rawMeanPvalue: number;
      rawDirectionalPvalue: number;
      adjustedMeanPvalue: number;
      adjustedDirectionalPvalue: number;
    };
  }>;
  validation: {
    protocol: string;
    purge: { periodsPerBoundary: number; totalPurgedPeriods: number; reason: string };
    multipleTesting: {
      method: string;
      selectionFamilySize: number;
      selectionCandidatesPassing10Pct: number;
      calibrationFamilySize: number;
    };
    calibrationInference: {
      meanRankIC: { mean: number; standardError: number; tStatistic: number; pValue: number; observations: number; hacLags: number };
      directionalPvalue: number;
      adjustedMeanPvalue: number;
      adjustedDirectionalPvalue: number;
    };
    portfolio: {
      construction: string;
      tailShare: number;
      periods: number;
      transactionCostBps: number;
      meanTurnover: number;
      gross: { mean: number; standardError: number; tStatistic: number; pValue: number; observations: number; hacLags: number };
      net: { mean: number; standardError: number; tStatistic: number; pValue: number; observations: number; hacLags: number };
    };
    walkForward: {
      protocol: string;
      frequency: DataFrequency;
      periodsPerYear: number;
      candidateDictionarySize: number;
      trainPeriods: number;
      selectionPeriods: number;
      calibrationPeriods: number;
      testBlockPeriods: number;
      refitIntervalPeriods: number;
      purgePeriodsPerBoundary: number;
      eligiblePeriods: number;
      excludedLeadingPartialPeriods: number;
      eligibleBlocks: number;
      evaluatedBlocks: number;
      evaluatedPeriods: number;
      maximumEvaluatedBlocks: number;
      truncated: boolean;
      estimatedCandidateObservationsPerBlock: number;
      estimatedRollingCandidateObservations: number;
      candidateObservationBudget: number;
      deployedBlocks: number;
      cashBlocks: number;
      meanTurnover: number;
      oosRankIC: { mean: number; standardError: number; tStatistic: number; pValue: number; observations: number; hacLags: number };
      positiveOosRankICShare: number;
      gross: { mean: number; standardError: number; tStatistic: number; pValue: number; observations: number; hacLags: number };
      net: { mean: number; standardError: number; tStatistic: number; pValue: number; observations: number; hacLags: number };
      blocks: Array<{
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
      }>;
      periods: Array<{
        block: number;
        testDate: string;
        calibrationPassed: boolean;
        activeComponents: number;
        oosRankIC: number | null;
        grossReturn: number;
        turnover: number;
        netReturn: number;
      }>;
    };
    gates: Array<{ id: string; label: string; passed: boolean; detail: string }>;
    passed: boolean;
  };
  interpretation: { gate: string; formalHoldoutIncluded: false; investmentAdvice: false };
};

export type WorkerMessage =
  | { type: "INSPECTION"; inspection: Inspection }
  | { type: "AUDIT_RESULT"; result: AuditResult }
  | { type: "PROGRESS"; progress: number; stage: string }
  | { type: "RESULT"; result: DiscoveryResult }
  | { type: "ERROR"; message: string };

export type Phase = "empty" | "inspecting" | "mapping" | "auditing" | "audited" | "running" | "complete" | "error";

export type AIProposal = {
  operation: "identity" | "square" | "lag1" | "change1" | "growth1" | "mean3" | "volatility3" | "difference" | "product" | "ratio";
  left_feature: string;
  right_feature: string | null;
  rationale_key: string;
  decision_authority: false;
};

