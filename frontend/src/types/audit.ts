/**
 * Audit records, reviewer reports, and version snapshots for the frontend.
 */

export type ReviewRecommendation = 'ready_to_merge' | 'requires_followup';

export interface ReviewerReport {
  id: string;
  task_id: string;
  agent_run_id: string;
  summary: string;
  strengths: string[];
  concerns: string[];
  security_audit: string;
  recommendation: ReviewRecommendation;
  task_understanding: string;
  implementation_summary: string;
  changed_files: Array<Record<string, unknown>>;
  requirements_coverage: Array<Record<string, unknown>>;
  behavior_verified: string[];
  tests_summary: Array<Record<string, unknown>>;
  test_failures: Array<Record<string, unknown>>;
  repair_summary: string[];
  remaining_risks: string[];
  unresolved_items: string[];
  evidence: Array<Record<string, unknown>>;
  final_status: string;
  created_at: string;
}

export interface ExecutionLog {
  id: string;
  agentRunId?: string;
  taskId: string;
  source: 'sandbox' | 'agent' | 'system';
  stream: 'stdout' | 'stderr' | 'event';
  logLine: string;
  loggedAt: string;
}

export interface GitSnapshot {
  id: string;
  workspaceId: string;
  taskId?: string;
  commitSha: string;
  treeSha: string;
  parentCommitSha?: string;
  message: string;
  createdAt: string;
}
