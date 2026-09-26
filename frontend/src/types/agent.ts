/**
 * Agent roles, execution statuses, and immutable run records.
 */

export type AgentRole = 'planner' | 'coder' | 'test_architect' | 'test_executor' | 'reviewer';

export type ExecutionStatus = 'queued' | 'running' | 'completed' | 'failed' | 'timeout' | 'cancelled';

export interface AgentRun {
  id: string;
  taskId: string;
  agentRole: AgentRole;
  loadoutId: string;
  workerId: string;
  providerId: string;
  modelName: string;
  startedAt: string;
  completedAt?: string;
  fallbackUsed: boolean;
  fallbackReason?: string;
  initialWorkerId?: string;
  executionStatus: ExecutionStatus;
  promptTokens?: number;
  completionTokens?: number;
  errorMessage?: string;
}

export interface AgentState {
  id: string;
  taskId: string;
  agentRole: AgentRole;
  statePayload: Record<string, unknown>;
  checkpointSeq: number;
  createdAt: string;
}
