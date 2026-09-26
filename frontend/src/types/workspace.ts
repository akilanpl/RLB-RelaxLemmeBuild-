/**
 * Workspace domain contracts for the frontend application.
 */

export type EnvironmentMode = 'sandboxed' | 'connected';

export type WorkspaceStatus = 'provisioning' | 'ready' | 'import_failed' | 'archived';

export interface Workspace {
  id: string;
  userId: string;
  name: string;
  slug: string;
  description?: string;
  environmentMode: EnvironmentMode;
  status: WorkspaceStatus;
  canonicalRootPath: string;
  fileCount: number;
  totalSizeBytes: number;
  currentSnapshotHash?: string;
  gitRemoteUrl?: string;
  isArchived: boolean;
  createdAt: string;
  updatedAt: string;
}


export interface StagingWorkspace {
  id: string;
  workspaceId: string;
  taskId: string;
  stagingRootPath: string;
  baseSnapshotHash: string;
  isActive: boolean;
  createdAt: string;
  discardedAt?: string;
}

export interface WorkspaceSettings {
  workspaceId: string;
  activeLoadoutId: string;
  sandboxCpuLimit: number;
  sandboxMemoryLimitMb: number;
  sandboxTimeoutSeconds: number;
  autoAnalyzeOnImport: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface DetectedTechnology {
  name: string;
  category: string;
  confidence: number;
  evidence: string[];
}

export interface ProjectDependency {
  name: string;
  version_spec?: string;
  dependency_type: 'production' | 'development';
  manifest_source: string;
}

export interface EntryPoint {
  path: string;
  entry_type: string;
  confidence: number;
  evidence: string[];
}

export interface DependencyGraphNode {
  id: string;
  node_type: string;
}

export interface DependencyGraphEdge {
  source: string;
  target: string;
  edge_type: string;
}

export interface DependencyGraph {
  nodes: DependencyGraphNode[];
  edges: DependencyGraphEdge[];
}

export interface IndexedFile {
  relative_path: string;
  extension: string;
  language: string;
  size_bytes: number;
  line_count: number;
  sha256_hash: string;
  is_binary: boolean;
  is_test_file: boolean;
}

export type AnalysisStatus = 'pending' | 'running' | 'completed' | 'failed' | 'stale';

export interface CodebaseAnalysisResult {
  id: string;
  workspace_id: string;
  analysis_version: number;
  status: AnalysisStatus;
  source_snapshot_hash?: string;
  summary: string;
  architecture_overview: string;
  primary_languages: string[];
  frameworks_detected: string[];
  technologies: DetectedTechnology[];
  dependencies: ProjectDependency[];
  entry_points: EntryPoint[];
  dependency_graph: DependencyGraph;
  warnings: string[];
  indexed_files: IndexedFile[];
  analysis_duration_ms: number;
  started_at: string;
  completed_at?: string;
  created_at: string;
}

// Retain legacy alias for compatibility
export type CodebaseAnalysis = CodebaseAnalysisResult;

