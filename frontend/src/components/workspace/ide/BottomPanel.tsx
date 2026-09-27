'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';
import { ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import FinalReviewPanel from '@/components/workspace/FinalReviewPanel';
import TestExecutionPanel from '@/components/workspace/TestExecutionPanel';
import { cn } from '@/lib/cn';

type Tab = 'terminal' | 'problems' | 'output' | 'tests' | 'review';

interface Props {
  taskId?: string | null;
  userId?: string;
  collapsed?: boolean;
  onToggle?: () => void;
  problems?: string[];
  outputLines?: string[];
}

export function BottomPanel({
  taskId,
  userId,
  collapsed = false,
  onToggle,
  problems = [],
  outputLines = [],
}: Props) {
  const [tab, setTab] = useState<Tab>('terminal');
  const [terminalLines, setTerminalLines] = useState<string[]>([]);
  const [terminalError, setTerminalError] = useState<string>();
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setTerminalLines([]);
    setTerminalError(undefined);
    if (!taskId || tab !== 'terminal' || collapsed) return;
    const load = async () => {
      try {
        const executions = await apiClient.getTestExecutions(taskId, userId);
        const latest = executions[executions.length - 1];
        if (active) {
          setTerminalLines(latest?.baseline_results.flatMap((result) => [
            `[${result.check_type}] ${result.status}`,
            result.stdout_output || '', result.stderr_output || '',
          ]).filter(Boolean) ?? []);
          setTerminalError(undefined);
        }
      } catch (err: unknown) {
        if (active) setTerminalError(err instanceof Error ? err.message : 'Unable to load sandbox output');
      } finally {
        if (active) timer = setTimeout(() => void load(), 3000);
      }
    };
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [taskId, userId, tab, collapsed]);


  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'terminal', label: 'Terminal' },
    { id: 'problems', label: 'Problems' },
    { id: 'output', label: 'Output' },
    { id: 'tests', label: 'Tests' },
    { id: 'review', label: 'Review' },
  ];

  return (
    <div className={cn('border-t border-cream/10 bg-[#0d151b] flex flex-col', collapsed ? 'h-9' : 'h-52')}>
      <div className="h-9 px-2 flex items-center gap-1 border-b border-cream/10 shrink-0">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => { setTab(t.id); if (collapsed) onToggle?.(); }}
            className={cn(
              'px-2.5 py-1 text-[10px] font-semibold tracking-wider rounded-full',
              tab === t.id && !collapsed ? 'bg-paper/10 text-cream' : 'text-cream/40 hover:text-cream/80',
            )}
          >
            {t.label}
          </button>
        ))}
        <button type="button" onClick={onToggle} className="ml-auto p-1 text-cream/40 hover:text-cream" aria-label={collapsed ? 'Expand panel' : 'Collapse panel'}>
          {collapsed ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>
      {!collapsed && (
        <div className="flex-1 overflow-auto p-3 text-xs font-mono text-meadow/80">
          {tab === 'terminal' && (
            <div className="space-y-1">
              {terminalError && <p className="text-coral">{terminalError}</p>}
              {terminalLines.length ? terminalLines.map((line, index) => <pre key={index} className="whitespace-pre-wrap break-words">{line}</pre>) : <p className="text-cream/35">No sandbox output yet. Command results appear after execution.</p>}
            </div>
          )}
          {tab === 'problems' && (
            problems.length === 0
              ? <p className="text-cream/35">No problems reported from the latest task run.</p>
              : (
                <ul className="space-y-1">
                  {problems.map((p, i) => <li key={i} className="text-coral">{p}</li>)}
                </ul>
              )
          )}
          {tab === 'output' && (
            outputLines.length === 0
              ? <p className="text-cream/35">No agent output yet.</p>
              : outputLines.map((line, i) => <div key={i}>{line}</div>)
          )}
          {tab === 'review' && (taskId ? <FinalReviewPanel taskId={taskId} userId={userId} /> : <p>No active task.</p>)}
          {tab === 'tests' && (
            taskId
              ? <TestExecutionPanel taskId={taskId} userId={userId} />
              : (
                <div className="flex items-center gap-2 text-cream/35">
                  <Loader2 className="w-3.5 h-3.5 opacity-40" />
                  No active task — tests appear after code approval.
                </div>
              )
          )}
        </div>
      )}
    </div>
  );
}
