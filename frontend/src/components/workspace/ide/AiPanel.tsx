'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { Loader2, Send, ShieldCheck } from 'lucide-react';
import type { PersistedPlan } from '@/types/workflow';
import TestExecutionPanel from '@/components/workspace/TestExecutionPanel';
import FinalReviewPanel from '@/components/workspace/FinalReviewPanel';
import { PENDING_PROMPT_KEY } from '@/components/dashboard/AICommandBar';
import { AgentActivity } from '@/components/ai/AgentActivity';

type TaskState = { id: string; title?: string; objective?: string; status: string } | null;

interface Props {
  workspaceId: string;
  userId?: string;
  displayName?: string;
  task: TaskState;
  plan: PersistedPlan | null;
  busyLabel?: string | null;
  error?: string | null;
  onCreateTask: (objective: string) => Promise<void>;
  onRunPlanner: () => Promise<void>;
  onPlanDecision: (decision: 'approved' | 'rejected' | 'revision_requested', feedback?: string) => Promise<void>;
  onRunCoder: () => Promise<void>;
  onTaskStatus: (status: string) => void;
  onShowDiff: () => void;
}

const STATUS_COPY: Record<string, string> = {
  ready: 'Ready for planning',
  analyzing: 'Analyzing repository…',
  staging_setup: 'Preparing isolated staging…',
  promoting: 'Publishing approved snapshot…',
  planning: 'Planner analyzing workspace…',
  plan_review: 'Plan ready for approval',
  coding: 'Coder preparing staged changes…',
  code_review: 'Code changes ready for review',
  test_planning: 'Test Architect building plan…',
  test_executing: 'Test Executor running sandbox tests…',
  repairing: 'Repairing from test failures…',
  reviewing: 'Reviewer preparing final audit…',
  completed: 'Task completed',
  cancelled: 'Task cancelled',
};

const SUGGESTIONS = [
  'Build a new feature',
  'Fix a bug',
  'Explain this code',
  'Write tests',
  'Refactor this component',
];

export function AiPanel({
  workspaceId,
  userId,
  displayName = 'Akilan',
  task,
  plan,
  busyLabel,
  error,
  onCreateTask,
  onRunPlanner,
  onPlanDecision,
  onRunCoder,
  onShowDiff,
}: Props) {
  const [input, setInput] = useState('');
  const [feedback, setFeedback] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const plannerAttempted = useRef<string | null>(null);

  useEffect(() => {
    try {
      const pending = window.sessionStorage.getItem(PENDING_PROMPT_KEY);
      if (pending) {
        setInput(pending);
        window.sessionStorage.removeItem(PENDING_PROMPT_KEY);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!task) return;
    if (task.status === 'ready' && !plan && plannerAttempted.current !== task.id) {
      plannerAttempted.current = task.id;
      void onRunPlanner();
    }
  }, [task?.id, task?.status, plan]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;
    setSubmitting(true);
    try {
      await onCreateTask(input.trim());
      setInput('');
    } finally {
      setSubmitting(false);
    }
  }

  const agentActive = busyLabel || (task ? STATUS_COPY[task.status] : null);

  return (
    <div className="h-full flex flex-col bg-[#121c24] border-l border-cream/10">
      <div className="h-11 px-3 flex items-center justify-between border-b border-cream/10">
        <span className="text-xs font-semibold tracking-tight text-cream">RLB AI</span>
        <span title={workspaceId} className="rounded-[8px] border border-cream/10 px-2 py-0.5 text-[10px] text-cream/45">
          default model
        </span>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3 text-sm">
        {!task && (
          <div className="rounded-2xl border border-cream/10 bg-paper/5 p-4 text-cream">
            <p className="text-base font-semibold">Hey {displayName} 👋</p>
            <p className="mt-1 text-sm text-cream/65">What are we building today?</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {SUGGESTIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setInput(item)}
                  className="rounded-[10px] bg-paper/10 px-3 py-1.5 text-[11px] text-cream/80 hover:bg-paper/15"
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        )}

        {task && (
          <div className="space-y-3">
            <div className="rounded-2xl bg-gold/10 border border-gold/20 p-3">
              <p className="text-[10px] uppercase tracking-wider text-gold/80 mb-1">You</p>
              <p className="text-cream text-xs whitespace-pre-wrap">{task.objective}</p>
            </div>

            <div className="rounded-2xl border border-cream/10 bg-paper/5 p-3 space-y-2">
              <div className="flex items-center gap-2 text-xs">
                {(busyLabel || ['planning', 'coding', 'test_planning', 'test_executing', 'reviewing'].includes(task.status)) ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-gold" />
                ) : (
                  <ShieldCheck className="w-3.5 h-3.5 text-meadow" />
                )}
                <span className="text-cream/80">{agentActive}</span>
              </div>
              <AgentActivity status={task.status} busyLabel={busyLabel} />
            </div>

            {plan && (
              <div className="rounded-2xl border border-cream/10 bg-[#0e161c] p-3 space-y-2 text-xs">
                <p className="font-semibold text-cream">Plan ready</p>
                <p className="text-cream/60">{plan.plan.understanding}</p>
                <p className="text-cream/40">{plan.plan.implementation_steps?.length || 0} implementation steps · {(plan.plan.affected_files || []).length} affected files · {(plan.plan.risks || []).length} risks</p>
                <ol className="list-decimal pl-4 space-y-1 text-cream/80">
                  {(plan.plan.implementation_steps || []).slice(0, 5).map((step) => (
                    <li key={step.order}>{step.description}</li>
                  ))}
                </ol>
                {task.status === 'plan_review' && (
                  <div className="space-y-2 pt-2 border-t border-cream/10">
                    <textarea
                      value={feedback}
                      onChange={(e) => setFeedback(e.target.value)}
                      placeholder="Revision feedback (optional)"
                      className="w-full rounded-2xl border border-cream/10 bg-[#121c24] p-2 text-xs text-cream"
                    />
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={Boolean(busyLabel)} onClick={() => onPlanDecision('revision_requested', feedback)} className="rounded-full bg-gold/80 px-2.5 py-1.5 text-[11px] font-semibold text-ink disabled:opacity-50">Request revision</button>
                      <button type="button" disabled={Boolean(busyLabel)} onClick={() => onPlanDecision('rejected')} className="rounded-full bg-coral px-2.5 py-1.5 text-[11px] font-semibold text-paper disabled:opacity-50">Reject</button>
                      <button type="button" disabled={Boolean(busyLabel)} onClick={() => onPlanDecision('approved')} className="rounded-full bg-meadow px-2.5 py-1.5 text-[11px] font-semibold text-paper disabled:opacity-50">Approve plan</button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {task.status === 'failed' && (
              <p className="rounded-2xl border border-coral/30 bg-coral/10 p-3 text-xs text-coral">
                This task failed. Review its workflow history and execution evidence before starting a new task. A failure does not approve a plan or code proposal.
              </p>
            )}

            {task.status === 'coding' && (
              <button type="button" disabled={Boolean(busyLabel)} onClick={onRunCoder} className="w-full rounded-full bg-coral px-3 py-2 text-xs font-semibold text-paper disabled:opacity-50">
                Generate code proposal
              </button>
            )}

            {task.status === 'code_review' && (
              <button type="button" onClick={onShowDiff} className="w-full rounded-full border border-gold/40 bg-gold/10 px-3 py-2 text-xs font-semibold text-gold">
                Review staged changes in the editor
              </button>
            )}

            {(task.status === 'test_planning' || task.status === 'test_executing' || task.status === 'repairing') && (
              <TestExecutionPanel taskId={task.id} userId={userId} />
            )}
            {task.status === 'reviewing' && <FinalReviewPanel taskId={task.id} userId={userId} />}
          </div>
        )}

        {error && <p className="text-xs text-coral">{error}</p>}
      </div>

      <form onSubmit={submit} className="border-t border-cream/10 p-3 space-y-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          rows={3}
          placeholder="Ask RLB anything..."
          aria-label="Ask RLB"
          className="w-full rounded-2xl border border-cream/10 bg-[#0e161c] px-3 py-2 text-xs text-cream outline-none focus:border-gold/40 resize-none"
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              if (input.trim() && !submitting) {
                void submit(event as unknown as FormEvent);
              }
            }
          }}
        />
        <button
          type="submit"
          disabled={submitting || !input.trim()}
          className="w-full inline-flex items-center justify-center gap-2 rounded-full bg-coral hover:brightness-105 px-3 py-2 text-xs font-semibold text-paper disabled:opacity-50"
        >
          {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          SEND
        </button>
      </form>
    </div>
  );
}
