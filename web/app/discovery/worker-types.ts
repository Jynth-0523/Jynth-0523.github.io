export type InspectRequest = { type: "INSPECT"; file: File };
export type AIProposal = {
  operation: "identity" | "square" | "lag1" | "change1" | "growth1" | "mean3" | "volatility3" | "difference" | "product" | "ratio";
  left_feature: string;
  right_feature: string | null;
  rationale_key: string;
  decision_authority: false;
};
export type DataFrequency = "daily" | "weekly" | "monthly" | "quarterly";
export type ResearchConfig = {
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
  aiProposals?: AIProposal[];
};
export type AuditRequest = { type: "AUDIT"; config: ResearchConfig };
export type RunRequest = { type: "RUN"; config: ResearchConfig };
export type RequestMessage = InspectRequest | AuditRequest | RunRequest;

export type Candidate = {
  id: string;
  operation: "identity" | "square" | "lag1" | "change1" | "growth1" | "mean3" | "volatility3" | "difference" | "product" | "ratio";
  family: "primitive" | "nonlinear" | "temporal" | "interaction";
  complexity: number;
  lookbackPeriods: number;
  source: "deterministic" | "ai-proposed";
  leftIndex: number;
  rightIndex: number;
  expression: string;
};

export type Period = {
  date: number;
  entities: string[];
  featureColumns: number[][];
  targetValues: number[];
  targetRanks: number[];
  observationCount: number;
  previousPeriod: Period | null;
  previousEntityIndex: Int32Array | null;
};

export type PeriodBucket = {
  entities: Set<string>;
  entityValues: string[];
  targets: number[];
  featureColumns: number[][];
};

export type Metrics = {
  meanRankIC: number;
  absMeanRankIC: number;
  icir: number;
  hitRate: number;
  stability: number;
  validPeriods: number;
  icSeries: number[];
};

