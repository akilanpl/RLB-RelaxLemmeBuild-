/**
 * Diff models for code proposals and Monaco editor rendering.
 */

export type DiffType = 'added' | 'modified' | 'deleted';

export interface Diff {
  id: string;
  codeProposalId: string;
  filePath: string;
  diffType: DiffType;
  unifiedDiff: string;
  additionsCount: number;
  deletionsCount: number;
  createdAt: string;
  beforeContent?: string;
  afterContent?: string;
}

export type ProposalStatus = 'ready_for_review' | 'revision_requested' | 'rejected' | 'approved';

export interface CodeProposal {
  id: string;
  task_id: string;
  agent_run_id: string;
  staging_workspace_id: string;
  summary: string;
  commit_message: string;
  diffs: ProposalDiff[];
  revision_number: number;
  base_snapshot_hash?: string;
  status: ProposalStatus | string;
  impact: { affected_files?: string[]; risks?: string[]; tests?: string[] } & Record<string, unknown>;
  warnings: string[];
  created_at: string;
  stale: boolean;
}

export interface ProposalDiff {
  id: string;
  file_path: string;
  diff_type: 'added' | 'modified' | 'deleted';
  unified_diff: string;
  additions_count: number;
  deletions_count: number;
  created_at: string;
  before_content: string;
  after_content: string;
}
