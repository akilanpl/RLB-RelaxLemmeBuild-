'use client';
import { useEffect, useState } from 'react';
import type { ReviewerReport } from '@/types/audit';
import { apiClient, ApiError } from '@/lib/api';

export default function FinalReviewPanel({ taskId, userId }: { taskId: string; userId?: string }) {
  const [report, setReport] = useState<ReviewerReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setReport(null);
    const load = async () => {
      setLoading(true);
      try {
        const next = await apiClient.getReviewerReport(taskId, userId);
        if (active) { setReport(next); setError(null); }
      } catch (err: unknown) {
        if (active && !(err instanceof ApiError && err.status === 404)) {
          setError(err instanceof Error ? err.message : 'Unable to load review');
        }
        if (active) timer = setTimeout(() => void load(), 3000);
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [taskId, userId]);
  return <section className="rounded-lg border border-slate-700 bg-slate-900 p-4">
    <h3 className="text-lg font-semibold text-slate-100">Final Review</h3>
    {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    {!report ? <p className="mt-3 text-sm text-slate-400">
      {loading ? 'Checking review…' : 'The worker publishes the final review after testing finishes.'}</p> :
      <div className="mt-3 space-y-3 text-sm text-slate-300">
        <p>{report.summary}</p>
        <p><strong>Final status:</strong> {report.final_status}</p>
        <p><strong>Task understanding:</strong> {report.task_understanding}</p>
        <p><strong>Implementation:</strong> {report.implementation_summary}</p>
        <div><strong>Requirements coverage</strong><ul className="list-disc pl-5">{(report.requirements_coverage ?? []).map((item, index) => <li key={index}>{String(item.requirement ?? 'Requirement')}: {String(item.status ?? 'unverified')} — {String(item.evidence ?? 'No evidence recorded')}</li>)}</ul></div>
        <div><strong>Behavior verified</strong><ul className="list-disc pl-5">{(report.behavior_verified ?? []).map(x => <li key={x}>{x}</li>)}</ul></div>
        <div><strong>Changed files</strong><ul className="list-disc pl-5">{(report.changed_files ?? []).map((item, index) => <li key={index}>{String(item.path ?? item.file ?? 'Unknown file')} {String(item.operation ?? '')}</li>)}</ul></div>
        <div><strong>Testing</strong><ul className="list-disc pl-5">{(report.tests_summary ?? []).map((item, index) => <li key={index}>{String(item.name ?? item.check ?? 'Check')}: {String(item.status ?? 'unverified')}</li>)}</ul></div>
        <div><strong>Strengths</strong><ul className="list-disc pl-5">{(report.strengths ?? []).map(x => <li key={x}>{x}</li>)}</ul></div>
        <div><strong>Concerns</strong><ul className="list-disc pl-5">{(report.concerns ?? []).map(x => <li key={x}>{x}</li>)}</ul></div>
        <p><strong>Security:</strong> {report.security_audit}</p>
        <div><strong>Risks / limitations</strong><ul className="list-disc pl-5">{(report.remaining_risks ?? []).map(x => <li key={x}>{x}</li>)}</ul></div>
        <div><strong>Repair history</strong><ul className="list-disc pl-5">{(report.repair_summary ?? []).map(x => <li key={x}>{x}</li>)}</ul></div>
        <p><strong>Recommendation:</strong> {report.recommendation}</p>
      </div>}
  </section>;
}
