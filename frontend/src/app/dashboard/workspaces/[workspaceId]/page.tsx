'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  ChevronDown,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Upload,
  FilePlus2,
  FolderOpen,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { apiClient } from '@/lib/api';
import { fetchUserWorkspaces } from '@/lib/auth';
import { entriesFromFileList, sanitizeImportEntries, validateImportPayload, validateZipFile } from '@/lib/importFiles';
import type { Workspace } from '@/types/workspace';
import type { PersistedPlan } from '@/types/workflow';
import { FileExplorer } from '@/components/workspace/ide/FileExplorer';
import { EditorPane, type EditorTab } from '@/components/workspace/ide/EditorPane';
import { AiPanel } from '@/components/workspace/ide/AiPanel';
import { BottomPanel } from '@/components/workspace/ide/BottomPanel';
import CodeProposalReview from '@/components/workspace/CodeProposalReview';
import { Avatar } from '@/components/ui/Avatar';

const OPEN_FILE_KEY = (id: string) => `rlb.ws.${id}.openFile`;

export default function WorkspaceIdePage() {
  const params = useParams();
  const router = useRouter();
  const workspaceId = params.workspaceId as string;
  const { user, profile, isAuthenticated, isLoading: authLoading, logout } = useAuth();

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [siblingWorkspaces, setSiblingWorkspaces] = useState<Workspace[]>([]);
  const [files, setFiles] = useState<Array<{ relative_path?: string; size_bytes?: number }>>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [centerMode, setCenterMode] = useState<'approved' | 'diff'>('approved');

  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [bottomCollapsed, setBottomCollapsed] = useState(false);

  const [task, setTask] = useState<{ id: string; title?: string; objective?: string; status: string } | null>(null);
  const [plan, setPlan] = useState<PersistedPlan | null>(null);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);

  const zipRef = useRef<HTMLInputElement>(null);
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated, router]);

  useEffect(() => {
    if (window.innerWidth < 768) {
      setLeftOpen(false);
      setRightOpen(false);
      setBottomCollapsed(true);
    }
  }, []);

  const loadWorkspaceData = useCallback(async () => {
    if (!workspaceId) return;
    setIsLoading(true);
    setError(null);
    try {
      const [wsData, filesData, latestTask] = await Promise.all([
        apiClient.getWorkspace(workspaceId, user?.id),
        apiClient.listWorkspaceFiles(workspaceId, user?.id),
        apiClient.getLatestTask(workspaceId, user?.id),
      ]);
      setWorkspace(wsData);
      setFiles(filesData);
      setTask(latestTask);
      if (user?.id) {
        fetchUserWorkspaces(user.id).then(setSiblingWorkspaces).catch(() => setSiblingWorkspaces([]));
      }

      if (latestTask) {
        const plans = await apiClient.listPlans(latestTask.id, user?.id);
        const latestPlan = [...plans].sort((a, b) => (b.revision_number || 0) - (a.revision_number || 0))[0] ?? null;
        setPlan(latestPlan);
      } else {
        setPlan(null);
      }

      const remembered = typeof window !== 'undefined' ? localStorage.getItem(OPEN_FILE_KEY(workspaceId)) : null;
      const first = remembered && filesData.some((f: { relative_path?: string }) => f.relative_path === remembered)
        ? remembered
        : filesData[0]?.relative_path ?? null;
      if (first) setActivePath(first);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load workspace');
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, user?.id]);

  useEffect(() => {
    if (isAuthenticated && workspaceId) void loadWorkspaceData();
  }, [isAuthenticated, workspaceId, loadWorkspaceData]);

  useEffect(() => {
    if (!task || !isAuthenticated) return;
    const active = ['ready', 'planning', 'coding', 'test_planning', 'test_executing', 'reviewing', 'repairing'].includes(task.status);
    if (!active) return;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const latest = await apiClient.getTask(task.id, user?.id);
          setTask(latest);
          if (latest.status === 'plan_review' || latest.status === 'planning') {
            const plans = await apiClient.listPlans(latest.id, user?.id);
            const latestPlan = [...plans].sort((a, b) => (b.revision_number || 0) - (a.revision_number || 0))[0] ?? null;
            if (latestPlan) setPlan(latestPlan);
          }
        } catch {
          // Keep the last known task if a poll fails.
        }
      })();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [task, isAuthenticated, user?.id]);

  useEffect(() => {
    if (!isAuthenticated || !workspaceId) return;
    const id = window.setInterval(async () => {
      const latest = await apiClient.getLatestTask(workspaceId, user?.id).catch(() => null);
      if (latest) {
        setTask((prev) => (prev && prev.id === latest.id && prev.status === latest.status ? prev : latest));
      }
    }, 12000);
    return () => window.clearInterval(id);
  }, [isAuthenticated, workspaceId, user?.id]);

  useEffect(() => {
    if (!workspaceId || !activePath) return;
    let alive = true;
    setLoadingContent(true);
    localStorage.setItem(OPEN_FILE_KEY(workspaceId), activePath);
    apiClient
      .getWorkspaceFileContent(workspaceId, activePath, user?.id)
      .then((res) => {
        if (!alive) return;
        setTabs((prev) => {
          const existing = prev.find((t) => t.path === activePath);
          if (existing) {
            return prev.map((t) => (t.path === activePath ? { ...t, content: res.content } : t));
          }
          return [...prev, { path: activePath, content: res.content }];
        });
      })
      .catch((err: unknown) => {
        if (!alive) return;
        const msg = err instanceof Error ? err.message : 'Failed to read file';
        setTabs((prev) => {
          if (prev.some((t) => t.path === activePath)) {
            return prev.map((t) => (t.path === activePath ? { ...t, content: `// Error: ${msg}` } : t));
          }
          return [...prev, { path: activePath, content: `// Error: ${msg}` }];
        });
      })
      .finally(() => {
        if (alive) setLoadingContent(false);
      });
    return () => { alive = false; };
  }, [workspaceId, activePath, user?.id]);

  const openFile = (path: string) => {
    setCenterMode('approved');
    setActivePath(path);
  };

  const closeTab = (path: string) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t.path !== path);
      if (activePath === path) {
        setActivePath(next[next.length - 1]?.path ?? null);
      }
      return next;
    });
  };

  const refreshFiles = async () => {
    const filesData = await apiClient.listWorkspaceFiles(workspaceId, user?.id);
    setFiles(filesData);
    const ws = await apiClient.getWorkspace(workspaceId, user?.id);
    setWorkspace(ws);
    return filesData;
  };

  const assertEmptyWorkspace = () => {
    if ((workspace?.fileCount || 0) > 0 || files.length > 0) {
      throw new Error(
        'Project import is only allowed for empty workspaces. Use staging/approval for changes to an active approved project.',
      );
    }
  };

  const handleImportZip = async (file: File) => {
    setImporting(true);
    setImportError(null);
    try {
      assertEmptyWorkspace();
      const zipError = validateZipFile(file);
      if (zipError) throw new Error(zipError);
      const ws = await apiClient.importWorkspaceZip(workspaceId, file, user?.id);
      setWorkspace(ws);
      const nextFiles = await refreshFiles();
      const first = nextFiles[0]?.relative_path;
      if (first) setActivePath(first);
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : 'ZIP import failed');
    } finally {
      setImporting(false);
    }
  };

  const handleImportFiles = async (entries: Array<{ file: File; relativePath: string }>) => {
    setImporting(true);
    setImportError(null);
    try {
      assertEmptyWorkspace();
      const { entries: cleaned } = sanitizeImportEntries(entries);
      const payloadError = validateImportPayload(cleaned);
      if (payloadError) throw new Error(payloadError);
      const ws = await apiClient.importWorkspaceFiles(workspaceId, cleaned, user?.id);
      setWorkspace(ws);
      const nextFiles = await refreshFiles();
      const first = nextFiles[0]?.relative_path;
      if (first) setActivePath(first);
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : 'File import failed');
    } finally {
      setImporting(false);
    }
  };

  const onCreateTask = async (objective: string) => {
    setBusyLabel('Creating task…');
    setTaskError(null);
    try {
      const created = await apiClient.createTask(workspaceId, objective, objective, user?.id);
      setTask(created);
      setPlan(null);
    } catch (err: unknown) {
      setTaskError(err instanceof Error ? err.message : 'Unable to create task');
      throw err;
    } finally {
      setBusyLabel(null);
    }
  };

  const onRunPlanner = async () => {
    if (!task) return;
    setBusyLabel('Planner analyzing workspace…');
    setTaskError(null);
    try {
      await apiClient.resumeTask(task.id);
      setTask(await apiClient.getTask(task.id, user?.id));
    } catch (err: unknown) {
      setTaskError(err instanceof Error ? err.message : 'Planner execution failed');
    } finally {
      setBusyLabel(null);
    }
  };

  const onPlanDecision = async (
    decision: 'approved' | 'rejected' | 'revision_requested',
    feedback?: string,
  ) => {
    if (!task) return;
    setBusyLabel('Submitting plan decision…');
    try {
      await apiClient.submitPlanApproval(task.id, decision, feedback, user?.id);
      setTask((current) =>
        current
          ? {
              ...current,
              status: decision === 'approved' ? 'coding' : decision === 'rejected' ? 'cancelled' : 'planning',
            }
          : current,
      );
      if (decision === 'revision_requested') setPlan(null);
    } catch (err: unknown) {
      setTaskError(err instanceof Error ? err.message : 'Unable to submit plan decision');
    } finally {
      setBusyLabel(null);
    }
  };

  const onRunCoder = async () => {
    if (!task) return;
    setBusyLabel('Coder generating staged changes…');
    setTaskError(null);
    try {
      await apiClient.resumeTask(task.id);
      setTask(await apiClient.getTask(task.id, user?.id));
    } catch (err: unknown) {
      setTaskError(err instanceof Error ? err.message : 'Coder execution failed');
    } finally {
      setBusyLabel(null);
    }
  };

  if (authLoading || isLoading) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 bg-[#101820]">
        <Loader2 className="w-7 h-7 text-gold animate-spin" />
        <p className="text-xs text-cream/50">Opening workspace…</p>
      </div>
    );
  }

  if (error || !workspace) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-4 px-6">
        <AlertCircle className="w-8 h-8 text-rose-400" />
        <p className="text-sm text-rose-300">{error || 'Workspace not found'}</p>
        <Link href="/dashboard/workspaces" className="text-xs text-gold hover:underline">
          Back to workspaces
        </Link>
      </div>
    );
  }

  const envLabel = workspace.environmentMode || 'sandboxed';
  const statusLabel = workspace.status || 'ready';
  const displayName = profile?.display_name || user?.user_metadata?.display_name || user?.email?.split('@')[0] || 'Akilan';

  const onRun = () => {
    setRightOpen(true);
    if (!task) return;
    if (task.status === 'ready' || task.status === 'planning') void onRunPlanner();
    else if (task.status === 'coding') void onRunCoder();
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-[#101820] text-cream">
      <header className="h-12 shrink-0 border-b border-cream/10 bg-[#121c24] flex items-center gap-2 px-2 sm:px-3">
        <Link href="/dashboard/workspaces" className="p-1.5 rounded-[10px] text-cream/50 hover:text-cream hover:bg-paper/10" title="Workspaces" aria-label="Back to workspaces">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <Link href="/dashboard" className="hidden sm:inline-flex h-7 w-7 items-center justify-center rounded-[8px] bg-coral text-[11px] font-bold text-paper">
          R
        </Link>
        <div className="relative min-w-0">
          <label className="flex items-center gap-1 rounded-[10px] border border-cream/10 bg-[#0e161c] px-2 py-1">
            <select
              aria-label="Switch workspace"
              value={workspace.id}
              onChange={(event) => router.push(`/dashboard/workspaces/${event.target.value}`)}
              className="max-w-[160px] truncate bg-transparent text-sm font-medium text-cream outline-none sm:max-w-[220px]"
            >
              {(siblingWorkspaces.length ? siblingWorkspaces : [workspace]).map((item) => (
                <option key={item.id} value={item.id} className="bg-[#121c24] text-cream">
                  {item.name}
                </option>
              ))}
            </select>
            <ChevronDown className="h-3.5 w-3.5 text-cream/40" />
          </label>
        </div>
        <span className="hidden items-center gap-1 text-[11px] text-meadow md:inline-flex">
          <Activity className="w-3 h-3" /> {statusLabel === 'ready' ? 'Ready' : statusLabel}
        </span>
        <span className="hidden text-[10px] px-1.5 py-0.5 rounded-[8px] bg-paper/10 text-cream/60 capitalize lg:inline">{envLabel}</span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={onRun}
            className="inline-flex items-center gap-1.5 rounded-[10px] bg-coral px-3 py-1.5 text-xs font-semibold text-paper hover:brightness-110"
          >
            <Play className="h-3.5 w-3.5" /> Run
          </button>
          {busyLabel && (
            <span className="hidden sm:inline-flex items-center gap-1.5 text-[10px] text-gold mr-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              Agent
            </span>
          )}
          <button type="button" onClick={() => setLeftOpen((v) => !v)} className="p-1.5 rounded-[10px] text-cream/40 hover:text-cream hover:bg-paper/10" title="Toggle explorer" aria-label="Toggle explorer">
            {leftOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
          </button>
          <button type="button" onClick={() => setRightOpen((v) => !v)} className="p-1.5 rounded-[10px] text-cream/40 hover:text-cream hover:bg-paper/10" title="Toggle RLB AI" aria-label="Toggle RLB AI">
            {rightOpen ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
          <button
            type="button"
            onClick={async () => { await logout(); router.push('/login'); }}
            className="ml-1"
            title="Sign out"
            aria-label="Sign out"
          >
            <Avatar name={displayName} size="sm" />
          </button>
        </div>
      </header>

      {(importError || importing) && (
        <div className={`px-3 py-1.5 text-[11px] border-b border-cream/10 ${importError ? 'bg-coral/15 text-coral' : 'bg-gold/10 text-gold'}`}>
          {importing ? 'Importing project into empty workspace…' : importError}
        </div>
      )}

      {/* Body */}
      <div className="flex-1 min-h-0 flex relative">
        {leftOpen && (
          <>
            <button type="button" className="absolute inset-0 z-10 bg-midnight/50 md:hidden" aria-label="Close explorer" onClick={() => setLeftOpen(false)} />
            <div className="w-[250px] shrink-0 absolute md:static inset-y-0 left-0 z-20 md:z-auto">
              <FileExplorer
                files={files}
                selectedPath={activePath}
                onSelect={(path) => { openFile(path); if (typeof window !== 'undefined' && window.innerWidth < 768) setLeftOpen(false); }}
                onRefresh={() => void refreshFiles()}
                onImportZip={(f) => void handleImportZip(f)}
                onImportFiles={(entries) => void handleImportFiles(entries)}
                importing={importing}
                gitRemoteUrl={workspace.gitRemoteUrl}
              />
            </div>
          </>
        )}

        <div className="flex-1 min-w-0 flex flex-col">
          <div className="flex-1 min-h-0">
            <EditorPane
              tabs={tabs}
              activePath={activePath}
              loading={loadingContent}
              mode={centerMode}
              onSelectTab={openFile}
              onCloseTab={closeTab}
              emptyActions={
                <>
                  <button type="button" onClick={() => zipRef.current?.click()} className="inline-flex items-center gap-1.5 rounded-full bg-coral px-3 py-1.5 text-xs font-semibold text-paper">
                    <Upload className="w-3.5 h-3.5" /> Upload ZIP
                  </button>
                  <button type="button" onClick={() => filesRef.current?.click()} className="inline-flex items-center gap-1.5 rounded-full border border-cream/15 bg-paper/5 px-3 py-1.5 text-xs font-semibold text-cream">
                    <FilePlus2 className="w-3.5 h-3.5" /> Add files
                  </button>
                  <button type="button" onClick={() => folderRef.current?.click()} className="inline-flex items-center gap-1.5 rounded-full border border-cream/15 bg-paper/5 px-3 py-1.5 text-xs font-semibold text-cream">
                    <FolderOpen className="w-3.5 h-3.5" /> Add folder
                  </button>
                  <button type="button" onClick={() => setRightOpen(true)} className="inline-flex items-center gap-1.5 rounded-full border border-cream/15 bg-paper/5 px-3 py-1.5 text-xs font-semibold text-cream">
                    Ask RLB to generate files
                  </button>
                </>
              }
              diffSlot={
                task ? (
                  <div className="h-full overflow-auto p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <p className="text-xs font-semibold text-cream">CODE REVIEW</p>
                      <button type="button" onClick={() => setCenterMode('approved')} className="text-[10px] text-cream/50 hover:text-cream">
                        Back to files
                      </button>
                    </div>
                    <CodeProposalReview
                      taskId={task.id}
                      userId={user?.id}
                      onStatusChange={(status) => setTask((current) => (current ? { ...current, status } : current))}
                      onApplied={() => {
                        void (async () => {
                          const [wsData, filesData] = await Promise.all([
                            apiClient.getWorkspace(workspaceId, user?.id),
                            apiClient.listWorkspaceFiles(workspaceId, user?.id),
                          ]);
                          setWorkspace(wsData);
                          setFiles(filesData);
                        })();
                      }}
                    />
                  </div>
                ) : null
              }
            />
          </div>
          <BottomPanel
            taskId={task?.id}
            userId={user?.id}
            collapsed={bottomCollapsed}
            onToggle={() => setBottomCollapsed((v) => !v)}
            outputLines={busyLabel ? [busyLabel] : plan ? [`Plan revision ${plan.revision_number} · ${plan.status}`] : []}
          />
        </div>

        {rightOpen && (
          <>
            <button type="button" className="absolute inset-0 z-10 bg-midnight/50 lg:hidden" aria-label="Close AI panel" onClick={() => setRightOpen(false)} />
            <div className="w-full max-w-[360px] shrink-0 absolute lg:static inset-x-0 bottom-0 top-auto h-[70%] lg:h-auto lg:inset-y-0 lg:right-0 lg:top-0 z-20 lg:z-auto rounded-t-[18px] lg:rounded-none overflow-hidden">
              <AiPanel
                workspaceId={workspaceId}
                userId={user?.id}
                displayName={displayName}
                task={task}
                plan={plan}
                busyLabel={busyLabel}
                error={taskError}
                onCreateTask={onCreateTask}
                onRunPlanner={onRunPlanner}
                onPlanDecision={onPlanDecision}
                onRunCoder={onRunCoder}
                onTaskStatus={(status) => setTask((current) => (current ? { ...current, status } : current))}
                onShowDiff={() => setCenterMode('diff')}
              />
            </div>
          </>
        )}
      </div>

      <input
        ref={zipRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        aria-hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) {
            void handleImportZip(f);
          }
          e.target.value = '';
        }}
      />
      <input
        ref={filesRef}
        type="file"
        multiple
        className="hidden"
        aria-hidden
        onChange={(e) => {
          void handleImportFiles(entriesFromFileList(e.target.files || []));
          e.target.value = '';
        }}
      />
      <input
        ref={folderRef}
        type="file"
        multiple
        className="hidden"
        aria-hidden
        // @ts-expect-error webkitdirectory is supported in Chromium
        webkitdirectory=""
        onChange={(e) => {
          void handleImportFiles(entriesFromFileList(e.target.files || []));
          e.target.value = '';
        }}
      />
    </div>
  );
}
