'use client';

import { useEffect, useState } from 'react';
import { apiClient, TestExecution, TestPlan } from '@/lib/api';

export default function TestExecutionPanel({ taskId, userId }: { taskId: string; userId?: string }) {
  const [plan, setPlan] = useState<TestPlan | null>(null);
  const [execution, setExecution] = useState<TestExecution | null>(null);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    Promise.all([apiClient.getTestPlan(taskId, userId), apiClient.getTestExecutions(taskId, userId)])
      .then(([nextPlan, executions]) => {
        if (active) {
          setPlan(nextPlan);
          setExecution(executions[executions.length - 1] ?? null);
        }
      })
      .catch((err: unknown) => active && setError(err instanceof Error ? err.message : 'Unable to load test results'));
    return () => { active = false; };
  }, [taskId, userId]);

  if (error) return <p className="text-xs text-rose-400">{error}</p>;
  if (!plan) return <p className="text-xs text-slate-500">Test plan has not been generated yet. Execution is not reported as passed.</p>;

  return (
    <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-950/40 p-4 text-xs">
      <div>
        <h3 className="font-semibold text-slate-200">TEST PLANNING</h3>
        <p className="mt-1 text-slate-400">{plan.plan_summary}</p>
      </div>
      <div className="space-y-2">
        {(plan.test_cases ?? []).map((testCase) => (
          <div key={testCase.id} className="rounded border border-slate-800 p-2">
            <p className="font-semibold text-slate-300">{testCase.title} <span className="text-[10px] uppercase text-indigo-300">{testCase.category}</span></p>
            <p className="mt-1 text-slate-500">{testCase.expected_result}</p>
          </div>
        ))}
      </div>
      {execution && (
        <div className="border-t border-slate-800 pt-3">
          <h3 className="font-semibold text-slate-200">TEST EXECUTING</h3>
          <p className={execution.all_passed ? 'mt-1 text-emerald-400' : 'mt-1 text-rose-400'}>
            {execution.all_passed ? 'Passed' : 'Failed'} · {execution.passed_tests}/{execution.total_tests} test cases
          </p>
          <div className="mt-2 grid gap-1 md:grid-cols-2">
            {(execution.baseline_results ?? []).map((result) => (
              <div key={result.check_type} className="flex justify-between rounded bg-slate-900 px-2 py-1 text-slate-400">
                <span>{result.check_type.replaceAll('_', ' ')}</span><span className={result.status === 'success' ? 'text-emerald-400' : result.status === 'not_applicable' ? 'text-slate-500' : 'text-rose-400'}>{result.status}</span>
              </div>
            ))}
          </div>
          {execution.failure_report && <p className="mt-2 text-rose-300">{execution.failure_report.summary}</p>}
        </div>
      )}
    </section>
  );
}
