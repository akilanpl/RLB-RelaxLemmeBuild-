/**
 * Test plans, baseline checks, and failure report contracts for the frontend.
 */

import { ExecutionStatus } from './agent';

export type BaselineCheckType =
  | 'dependency_install'
  | 'type_check'
  | 'lint'
  | 'production_build'
  | 'unit_integration_tests'
  | 'health_check';

export type TestCaseCategory = 'functional' | 'regression' | 'edge_case' | 'security';

export interface TestCase {
  id: string;
  testPlanId: string;
  category: TestCaseCategory;
  title: string;
  description: string;
  expectedResult: string;
  testCode: string;
  createdAt: string;
}

export interface TestPlan {
  id: string;
  taskId: string;
  agentRunId: string;
  planSummary: string;
  testCases: TestCase[];
  createdAt: string;
}

export interface BuildResult {
  id: string;
  testExecutionId: string;
  checkType: BaselineCheckType;
  status: ExecutionStatus;
  exitCode: number;
  stdoutOutput?: string;
  stderrOutput?: string;
  durationMs: number;
  createdAt: string;
}

export interface FailedCheckDetail {
  checkName: string;
  errorSummary: string;
  exitCode: number;
  tracebackOrLogs: string;
}

export interface FailureReport {
  summary: string;
  failedBaselineChecks: FailedCheckDetail[];
  failedTestCases: FailedCheckDetail[];
  remediationSuggestions: string[];
}

export interface TestExecution {
  id: string;
  taskId: string;
  agentRunId: string;
  allPassed: boolean;
  totalTests: number;
  passedTests: number;
  failedTests: number;
  executionDurationMs: number;
  baselineResults: BuildResult[];
  failureReport?: FailureReport;
  createdAt: string;
}
