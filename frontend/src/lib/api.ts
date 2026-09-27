import {
  CodebaseAnalysisResult,
  DetectedTechnology,
  DependencyGraph,
  Workspace,
} from '@/types/workspace';
import type { PersistedPlan, Task } from '@/types/workflow';

export interface TestPlan {
  id: string;
  task_id: string;
  agent_run_id: string;
  plan_summary: string;
  test_cases: Array<{ id: string; category: string; title: string; description: string; expected_result: string }>;
  created_at: string;
}

export interface TestExecution {
  id: string;
  task_id: string;
  all_passed: boolean;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  baseline_results: Array<{ check_type: string; status: string; stdout_output?: string; stderr_output?: string }>;
  failure_report?: { summary: string; failed_baseline_checks: Array<{ check_name: string; traceback_or_logs: string }>; failed_test_cases: Array<{ check_name: string; traceback_or_logs: string }> };
  created_at: string;
}
import type { CodeProposal } from '@/types/diff';
import type { ReviewerReport } from '@/types/audit';

export interface SystemHealth {
  status: string;
  project: string;
  environment: string;
}

export interface DatabaseHealth {
  configured: boolean;
  connected: boolean;
  latency_ms: number | null;
  message: string;
}

export interface FullHealth {
  status: string;
  project: string;
  environment: string;
  database: DatabaseHealth;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function parseErrorMessage(errorText: string, fallback: string): string {
  if (!errorText) return fallback;
  try {
    const jsonError = JSON.parse(errorText) as { detail?: unknown; message?: unknown };
    const detail = jsonError.detail ?? jsonError.message;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === 'string') return item;
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg);
          }
          return JSON.stringify(item);
        })
        .filter(Boolean)
        .join('; ') || fallback;
    }
    if (detail && typeof detail === 'object') {
      return JSON.stringify(detail);
    }
  } catch {
    /* not JSON */
  }
  return errorText.length > 500 ? fallback : errorText;
}

export function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function normalizeWorkspace(item: unknown): Workspace | null {
  if (!item || typeof item !== 'object') {
    return null;
  }
  const row = item as Record<string, unknown>;
  const id = row.id;
  const name = row.name;
  if (id == null || typeof name !== 'string') {
    return null;
  }
  return {
    id: String(id),
    userId: String(row.user_id ?? row.userId ?? ''),
    name,
    slug: String(row.slug ?? ''),
    description: (row.description as string | undefined) ?? undefined,
    environmentMode: ((row.environment_mode ?? row.environmentMode ?? 'sandboxed') as Workspace['environmentMode']),
    status: ((row.status ?? 'ready') as Workspace['status']),
    canonicalRootPath: String(row.canonical_root_path ?? row.canonicalRootPath ?? ''),
    fileCount: Number(row.file_count ?? row.fileCount ?? 0),
    totalSizeBytes: Number(row.total_size_bytes ?? row.totalSizeBytes ?? 0),
    currentSnapshotHash: (row.current_snapshot_hash ?? row.currentSnapshotHash) as string | undefined,
    gitRemoteUrl: (row.git_remote_url ?? row.gitRemoteUrl) as string | undefined,
    isArchived: Boolean(row.is_archived ?? row.isArchived ?? false),
    createdAt: String(row.created_at ?? row.createdAt ?? ''),
    updatedAt: String(row.updated_at ?? row.updatedAt ?? ''),
  };
}

export function normalizeWorkspaceList(value: unknown): Workspace[] {
  return asArray(value).map(normalizeWorkspace).filter((item): item is Workspace => item !== null);
}

async function getAccessToken(): Promise<string | null> {
  try {
    const { getSupabaseClient } = await import('@/lib/supabase');
    const client = getSupabaseClient();
    if (!client) return null;
    const { data } = await client.auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

class ApiClient {
  private baseUrl: string;

  constructor() {
    this.baseUrl =
      process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    try {
      const isFormData = options.body instanceof FormData;
      const headers: Record<string, string> = {
        Accept: 'application/json',
        ...(options.headers as Record<string, string>),
      };

      if (!headers.Authorization && !headers.authorization) {
        const token = await getAccessToken();
        if (token) {
          headers.Authorization = `Bearer ${token}`;
        }
      }

      if (!isFormData && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }
      const response = await fetch(url, {
        ...options,
        headers,
      });

      const bodyText = await response.text();

      if (!response.ok) {
        throw new ApiError(
          response.status,
          response.statusText,
          parseErrorMessage(bodyText, response.statusText || 'Request failed'),
        );
      }

      if (!bodyText.trim()) {
        return undefined as T;
      }

      try {
        return JSON.parse(bodyText) as T;
      } catch {
        throw new ApiError(502, 'Bad Gateway', 'The server returned a non-JSON response.');
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        throw err;
      }
      const message = err instanceof Error ? err.message : 'Unknown network failure';
      throw new ApiError(0, 'NetworkError', message);
    }
  }

  /**
   * Fetches backend process health.
   */
  async resumeTask(taskId: string): Promise<void> {
    await this.request(`/api/v1/tasks/${taskId}/resume`, { method: 'POST' });
  }

  async getHealth(): Promise<SystemHealth> {
    return this.request<SystemHealth>('/health');
  }

  /**
   * Fetches database connectivity diagnostics without exposing credentials.
   */
  async getDatabaseHealth(): Promise<DatabaseHealth> {
    return this.request<DatabaseHealth>('/health/db');
  }

  /**
   * Fetches combined system and database diagnostic status.
   */
  async getFullHealth(): Promise<FullHealth> {
    return this.request<FullHealth>('/health/full');
  }

  async getQueueHealth(): Promise<{ status: string; configured: boolean }> {
    return this.request('/health/queue');
  }

  async getStorageHealth(): Promise<{ status: string; configured: boolean }> {
    return this.request('/health/storage');
  }

  async getSandboxHealth(): Promise<{ status: string; configured: boolean }> {
    return this.request('/health/sandbox');
  }

  async createTask(workspaceId: string, title: string, objective: string, userId?: string): Promise<Task> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request<Task>('/api/v1/tasks', {
      method: 'POST',
      headers,
      body: JSON.stringify({ workspace_id: workspaceId, title, objective }),
    });
  }

  async getTask(taskId: string, userId?: string): Promise<Task> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request<Task>(`/api/v1/tasks/${taskId}`, { headers });
  }

  async getLatestTask(workspaceId: string, userId?: string): Promise<Task | null> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    try {
      return await this.request<Task>(`/api/v1/tasks/workspace/${workspaceId}/latest`, { headers });
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  }

  async listTaskRuns(taskId: string, userId?: string): Promise<unknown[]> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return asArray(await this.request<unknown[]>(`/api/v1/tasks/${taskId}/agent-runs`, { headers }));
  }

  async runPlanner(taskId: string, revisionFeedback?: string, userId?: string): Promise<PersistedPlan> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request<PersistedPlan>(`/api/v1/tasks/${taskId}/planner`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ revision_feedback: revisionFeedback ?? null }),
    });
  }

  async listPlans(taskId: string, userId?: string): Promise<PersistedPlan[]> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    try {
      return asArray(await this.request<PersistedPlan[]>(`/api/v1/tasks/${taskId}/plans`, { headers }));
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) return [];
      throw err;
    }
  }

  async submitPlanApproval(taskId: string, approvalStatus: 'approved' | 'rejected' | 'revision_requested', feedback?: string, userId?: string): Promise<unknown> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request(`/api/v1/tasks/${taskId}/approvals`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ approval_type: 'plan_approval', status: approvalStatus, feedback: feedback ?? null }),
    });
  }

  async listCodeProposals(taskId: string, userId?: string): Promise<CodeProposal[]> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return asArray(await this.request<CodeProposal[]>(`/api/v1/tasks/${taskId}/code-proposals`, { headers }));
  }

  async getCodeProposal(proposalId: string, userId?: string): Promise<CodeProposal> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request<CodeProposal>(`/api/v1/tasks/code-proposals/${proposalId}`, { headers });
  }

  async runCoder(taskId: string, revisionFeedback?: string, userId?: string): Promise<CodeProposal> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request<CodeProposal>(`/api/v1/tasks/${taskId}/coder`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ revision_feedback: revisionFeedback ?? null }),
    });
  }

  async approveCodeProposal(proposalId: string, userId?: string): Promise<unknown> {
    return this.proposalAction(`/api/v1/tasks/code-proposals/${proposalId}/approve`, userId);
  }

  async rejectCodeProposal(proposalId: string, userId?: string): Promise<unknown> {
    return this.proposalAction(`/api/v1/tasks/code-proposals/${proposalId}/reject`, userId);
  }

  async requestCodeProposalRevision(proposalId: string, feedback: string, userId?: string): Promise<unknown> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request(`/api/v1/tasks/code-proposals/${proposalId}/revision`, {
      method: 'POST', headers, body: JSON.stringify({ feedback }),
    });
  }

  async getTestPlan(taskId: string, userId?: string): Promise<TestPlan | null> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    try {
      return await this.request<TestPlan>(`/api/v1/tasks/${taskId}/test-plans`, { headers });
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  }

  async getTestExecutions(taskId: string, userId?: string): Promise<TestExecution[]> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return asArray(await this.request<TestExecution[]>(`/api/v1/tasks/${taskId}/test-executions`, { headers }));
  }

  async runReviewer(taskId: string, userId?: string): Promise<ReviewerReport> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request<ReviewerReport>(`/api/v1/tasks/${taskId}/review`, { method: 'POST', headers });
  }

  async getReviewerReport(taskId: string, userId?: string): Promise<ReviewerReport> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request<ReviewerReport>(`/api/v1/tasks/${taskId}/review`, { headers });
  }

  private async proposalAction(endpoint: string, userId?: string): Promise<unknown> {
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    return this.request(endpoint, { method: 'POST', headers });
  }

  /**
   * Provisions a new workspace (empty or via ZIP file upload).
   */
  async createWorkspace(formData: FormData, userId?: string): Promise<Workspace> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    const workspace = normalizeWorkspace(
      await this.request<unknown>('/api/v1/workspaces', {
        method: 'POST',
        body: formData,
        headers,
      })
    );
    if (!workspace) {
      throw new ApiError(502, 'Bad Gateway', 'Workspace response was malformed.');
    }
    return workspace;
  }

  /**
   * Lists all workspaces owned by the user.
   */
  async listWorkspaces(userId?: string): Promise<Workspace[]> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    return normalizeWorkspaceList(await this.request<unknown>('/api/v1/workspaces', { headers }));
  }

  /**
   * Fetches details of a specific workspace.
   */
  async getWorkspace(workspaceId: string, userId?: string): Promise<Workspace> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    const workspace = normalizeWorkspace(
      await this.request<unknown>(`/api/v1/workspaces/${workspaceId}`, { headers })
    );
    if (!workspace) {
      throw new ApiError(502, 'Bad Gateway', 'Workspace response was malformed.');
    }
    return workspace;
  }

  /**
   * Lists all files tracked in an approved workspace.
   */
  async listWorkspaceFiles(workspaceId: string, userId?: string): Promise<Array<{ relative_path: string; size_bytes: number }>> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    return asArray(await this.request<unknown>(`/api/v1/workspaces/${workspaceId}/files`, { headers }));
  }

  /**
   * Reads the contents of a file from approved workspace canonical storage.
   */
  async getWorkspaceFileContent(
    workspaceId: string,
    path: string,
    userId?: string
  ): Promise<{ path: string; content: string; size_bytes: number; is_binary: boolean }> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    const query = new URLSearchParams({ path }).toString();
    return this.request<{ path: string; content: string; size_bytes: number; is_binary: boolean }>(
      `/api/v1/workspaces/${workspaceId}/files/content?${query}`,
      { headers }
    );
  }

  async importWorkspaceZip(workspaceId: string, file: File, userId?: string): Promise<Workspace> {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    const workspace = normalizeWorkspace(
      await this.request<unknown>(`/api/v1/workspaces/${workspaceId}/import/zip`, {
        method: 'POST',
        body: formData,
        headers,
      })
    );
    if (!workspace) throw new ApiError(502, 'Bad Gateway', 'Import response was malformed.');
    return workspace;
  }

  async importWorkspaceFiles(
    workspaceId: string,
    entries: Array<{ file: File; relativePath: string }>,
    userId?: string
  ): Promise<Workspace> {
    const formData = new FormData();
    for (const entry of entries) {
      const filename = entry.file.name || entry.relativePath.split('/').pop() || 'file';
      formData.append('files', entry.file, filename);
      formData.append('paths', entry.relativePath);
    }
    const headers: Record<string, string> = {};
    if (userId) headers['x-user-id'] = userId;
    const workspace = normalizeWorkspace(
      await this.request<unknown>(`/api/v1/workspaces/${workspaceId}/import/files`, {
        method: 'POST',
        body: formData,
        headers,
      })
    );
    if (!workspace) throw new ApiError(502, 'Bad Gateway', 'Import response was malformed.');
    return workspace;
  }

  /**
   * Triggers or re-triggers deterministic codebase analysis.
   */
  async triggerAnalysis(
    workspaceId: string,
    force: boolean = false,
    userId?: string
  ): Promise<CodebaseAnalysisResult> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    const query = force ? '?force=true' : '';
    return this.request<CodebaseAnalysisResult>(
      `/api/v1/workspaces/${workspaceId}/analysis${query}`,
      {
        method: 'POST',
        headers,
      }
    );
  }

  /**
   * Fetches latest codebase analysis for an approved workspace.
   */
  async getWorkspaceAnalysis(
    workspaceId: string,
    userId?: string
  ): Promise<CodebaseAnalysisResult> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    return this.request<CodebaseAnalysisResult>(
      `/api/v1/workspaces/${workspaceId}/analysis`,
      { headers }
    );
  }

  /**
   * Fetches project architectural summary.
   */
  async getWorkspaceAnalysisSummary(
    workspaceId: string,
    userId?: string
  ): Promise<Record<string, unknown>> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    return this.request<Record<string, unknown>>(
      `/api/v1/workspaces/${workspaceId}/analysis/summary`,
      { headers }
    );
  }

  /**
   * Fetches dependency graph.
   */
  async getWorkspaceAnalysisGraph(
    workspaceId: string,
    userId?: string
  ): Promise<DependencyGraph> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    return this.request<DependencyGraph>(
      `/api/v1/workspaces/${workspaceId}/analysis/graph`,
      { headers }
    );
  }

  /**
   * Fetches detected technologies with evidence and confidence scores.
   */
  async getWorkspaceAnalysisTechnologies(
    workspaceId: string,
    userId?: string
  ): Promise<DetectedTechnology[]> {
    const headers: Record<string, string> = {};
    if (userId) {
      headers['x-user-id'] = userId;
    }
    return asArray(
      await this.request<unknown>(
        `/api/v1/workspaces/${workspaceId}/analysis/technologies`,
        { headers }
      )
    );
  }

  async listProviders(): Promise<Array<{ id: string; name: string }>> {
    return asArray(await this.request<unknown>('/api/v1/providers'));
  }

  async listProviderCredentials(): Promise<Array<{
    id: string;
    provider_id: string;
    provider_name?: string;
    key_fingerprint: string;
  }>> {
    return asArray(await this.request<unknown>('/api/v1/providers/credentials'));
  }

  async saveProviderCredential(providerName: string, apiKey: string, extra?: { label?: string; baseUrl?: string }): Promise<{
    id: string;
    provider_id: string;
    provider_name?: string;
    product_label?: string;
    key_fingerprint: string;
  }> {
    return this.request('/api/v1/providers/credentials', {
      method: 'PUT',
      body: JSON.stringify({
        provider_name: providerName,
        api_key: apiKey,
        label: extra?.label,
        base_url: extra?.baseUrl,
      }),
    });
  }

  async deleteProviderCredential(providerId: string): Promise<void> {
    await this.request(`/api/v1/providers/credentials/${encodeURIComponent(providerId)}`, { method: 'DELETE' });
  }

  async listProviderCatalog(): Promise<Array<{ id: string; name: string; product_label: string; default_model: string }>> {
    return asArray(await this.request<unknown>('/api/v1/providers/catalog'));
  }

  async listWorkers(): Promise<Array<{
    id: string;
    provider_id: string;
    provider_name?: string;
    product_label?: string;
    model_name: string;
    credential_id?: string;
  }>> {
    return asArray(await this.request<unknown>('/api/v1/providers/workers'));
  }

  async saveWorker(input: { model_name: string; provider_id?: string; credential_id?: string }): Promise<{
    id: string;
    provider_id: string;
    provider_name?: string;
    model_name: string;
    credential_id?: string;
  }> {
    return this.request('/api/v1/providers/workers', {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  }

  async listLoadouts(): Promise<Array<{
    id: string;
    name: string;
    mappings: Record<string, { primary_worker_id: string; fallback_worker_ids?: string[] }>;
  }>> {
    return asArray(await this.request<unknown>('/api/v1/providers/loadouts'));
  }

  async saveLoadout(input: {
    id?: string;
    name: string;
    mappings: Record<string, { primary_worker_id: string; fallback_worker_ids?: string[] }>;
  }): Promise<{ id: string; name: string; mappings: Record<string, { primary_worker_id: string }> }> {
    if (input.id) {
      return this.request(`/api/v1/providers/loadouts/${input.id}`, {
        method: 'PUT',
        body: JSON.stringify({ name: input.name, mappings: input.mappings }),
      });
    }
    return this.request('/api/v1/providers/loadouts', {
      method: 'POST',
      body: JSON.stringify({ name: input.name, mappings: input.mappings }),
    });
  }
}

export const apiClient = new ApiClient();
