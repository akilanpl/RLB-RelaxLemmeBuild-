/**
 * Workflow states, approval gates, and task contracts.
 */

import { Diff } from './diff';

export type TaskStatus =
  | 'idle'
  | 'analyzing'
  | 'ready'
  | 'planning'
  | 'plan_review'
  | 'staging_setup'
  | 'coding'
  | 'code_review'
  | 'staging_cleanup'
  | 'promoting'
  | 'test_planning'
  | 'test_executing'
  | 'reviewing'
  | 'completed'
  | 'cancelled'
  | 'failed';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'revision_requested';
export type ApprovalGateType = 'plan_approval' | 'code_approval';

export interface Task {
  id: string;
  workspaceId: string;
  conversationId: string;
  userPrompt: string;
  status: TaskStatus;
  activeLoadoutId: string;
  workerOverrides?: Record<string, string>;
  activeStagingWorkspaceId?: string;
  createdAt: string;
  updatedAt: string;
  title?: string;
  objective?: string;
  userId?: string;
  version?: number;
  approvedSnapshotHash?: string;
}

export interface PlanStep {
  stepNumber: number;
  title: string;
  description: string;
  targetFiles: string[];
}

export interface Plan {
  id: string;
  taskId: string;
  agentRunId: string;
  title: string;
  summary: string;
  steps: PlanStep[];
  affectedFiles: string[];
  riskAssessment?: string;
  revisionNumber: number;
  createdAt: string;
}

export interface ImplementationPlan {
  objective: string;
  understanding: string;
  implementation_steps: Array<{
    order: number;
    description: string;
    rationale: string;
    candidate_files: string[];
  }>;
  affected_files: string[];
  dependencies: string[];
  risks: string[];
  assumptions: string[];
  expected_behavior: string;
  unresolved_questions: string[];
}

export interface PersistedPlan {
  id: string;
  task_id: string;
  agent_run_id: string;
  revision_number: number;
  plan: ImplementationPlan;
  source_snapshot_hash?: string;
  status: string;
  created_at: string;
}

export interface Approval {
  id: string;
  taskId: string;
  gateType: ApprovalGateType;
  status: ApprovalStatus;
  userFeedback?: string;
  reviewedBy: string;
  createdAt: string;
  resolvedAt?: string;
}

export interface CodeProposal {
  id: string;
  taskId: string;
  agentRunId: string;
  stagingWorkspaceId: string;
  summary: string;
  commitMessage: string;
  diffs: Diff[];
  revisionNumber: number;
  createdAt: string;
}
