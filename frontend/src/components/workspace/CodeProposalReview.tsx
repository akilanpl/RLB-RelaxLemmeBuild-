'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileCode2, Loader2, XCircle } from 'lucide-react';
import { apiClient } from '@/lib/api';
import type { CodeProposal } from '@/types/diff';

const DiffEditor = dynamic(
  () => import('@monaco-editor/react').then((module) => {
    module.loader.config({ paths: { vs: '/monaco/vs' } });
    return module.DiffEditor;
  }),
  { ssr: false, loading: () => <div className="h-72 flex items-center justify-center text-slate-500"><Loader2 className="w-5 h-5 animate-spin mr-2" />Loading diff editor...</div> },
);

interface Props {
  taskId: string;
  userId?: string;
  onStatusChange?: (status: 'coding' | 'cancelled' | 'test_planning' | 'promoting') => void;
  onApplied?: () => void;
}

export default function CodeProposalReview({ taskId, userId, onStatusChange, onApplied }: Props) {
  const [proposals, setProposals] = useState<CodeProposal[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [actionLabel, setActionLabel] = useState<string>();

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setProposals(await apiClient.listCodeProposals(taskId, userId));
      setError(undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load code proposals');
    } finally {
      setLoading(false);
    }
  }, [taskId, userId]);
  useEffect(() => { void load(); }, [load]);

  const proposal = proposals.find((item) => item.id === selectedId) ?? proposals[0];
  const diffs = useMemo(() => Array.isArray(proposal?.diffs) ? proposal.diffs : [], [proposal?.diffs]);
  const warnings = Array.isArray(proposal?.warnings) ? proposal.warnings : [];
  const [filePath, setFilePath] = useState<string>();
  const diff = useMemo(
    () => diffs.find((item) => item.file_path === filePath) ?? diffs[0],
    [diffs, filePath],
  );
  useEffect(() => { setFilePath(diffs[0]?.file_path); }, [diffs]);

  const action = async (kind: 'approve' | 'reject' | 'revision') => {
    if (!proposal) return;
    if (kind === 'revision' && !feedback.trim()) return;
    setBusy(true); setError(undefined);
    setActionLabel(kind === 'approve' ? 'Applying approved changes...' : kind === 'reject' ? 'Rejecting proposal...' : 'Submitting revision request...');
    try {
      if (kind === 'approve') {
        await apiClient.approveCodeProposal(proposal.id, userId);
        onStatusChange?.('promoting');
        onApplied?.();
      }
      if (kind === 'reject') {
        await apiClient.rejectCodeProposal(proposal.id, userId);
        onStatusChange?.('cancelled');
      }
      if (kind === 'revision') {
        await apiClient.requestCodeProposalRevision(proposal.id, feedback.trim(), userId);
        onStatusChange?.('coding');
      }
      setFeedback('');
      await load();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to update proposal';
      setError(message.includes('changed') || message.includes('stale')
        ? 'The approved workspace changed after this proposal was created. The proposal cannot be applied until it is regenerated.'
        : message);
    } finally {
      setBusy(false);
      setActionLabel(undefined);
    }
  };

  if (loading) return <section className="rounded-2xl border border-cream/10 bg-[#0e161c] p-6 text-xs text-cream/40"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Loading proposal...</section>;
  if (!proposal && !error) return null;
  const additions = diffs.reduce((total, item) => total + (item.additions_count || 0), 0);
  const deletions = diffs.reduce((total, item) => total + (item.deletions_count || 0), 0);
  const impact = proposal?.impact ?? {};
  return (
    <section className="rounded-2xl border border-cream/10 bg-[#0e161c] p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-cream">RLB prepared some changes.</h3>
          <p className="text-xs text-cream/50">Review staged changes before they reach canonical storage.</p>
          {proposal && <p className="mt-2 text-xs text-cream/60"><span className="text-meadow">+{additions}</span> · <span className="text-coral">-{deletions}</span> · {diffs.length} files</p>}
        </div>
        {proposal && <span className="rounded-full bg-gold/15 px-2 py-1 text-[10px] font-mono text-gold">REVISION {proposal.revision_number} · {proposal.status}</span>}
      </div>
      {error && <p className="text-xs text-rose-400">{error}</p>}
      {proposal && (
        <>
          {proposal.stale && <div className="flex gap-2 rounded border border-amber-700/50 bg-amber-950/30 p-2 text-xs text-amber-200"><AlertTriangle className="h-4 w-4 shrink-0" />This proposal is stale because the workspace changed after it was generated. Regenerate it before approving.</div>}
          {proposals.length > 1 && <select value={proposal.id} onChange={(event) => setSelectedId(event.target.value)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300">{proposals.map((item) => <option key={item.id} value={item.id}>Proposal v{item.revision_number} · {item.status}{item.id === proposals[0].id ? ' · current' : ''}</option>)}</select>}
          <div className="grid gap-3 md:grid-cols-[220px_1fr]">
            <div className="space-y-2">
              <p className="text-xs font-semibold text-slate-400">Changed files</p>
              {diffs.map((item) => <button type="button" key={item.id} onClick={() => setFilePath(item.file_path)} className={`flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs ${item.file_path === diff?.file_path ? 'bg-indigo-600/20 text-indigo-200' : 'text-slate-400 hover:bg-slate-800'}`}><FileCode2 className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{item.file_path}</span><span className="text-[9px] uppercase text-slate-500">{item.diff_type}</span><span className="ml-auto text-[10px] text-emerald-400">+{item.additions_count} / -{item.deletions_count}</span></button>)}
            </div>
            <div className="overflow-hidden rounded border border-slate-800">
              {diff ? <DiffEditor height="360px" language={diff.file_path.endsWith('.json') ? 'json' : 'typescript'} original={diff.before_content} modified={diff.after_content} theme="vs-dark" options={{ readOnly: true, minimap: { enabled: false }, renderSideBySide: true }} /> : <div className="p-8 text-center text-xs text-slate-500">No file changes.</div>}
            </div>
          </div>
          <div className="grid gap-3 text-xs md:grid-cols-2">
            <div><p className="font-semibold text-slate-300">Summary</p><p className="mt-1 text-slate-400">{proposal.summary}</p><p className="mt-2 text-slate-500">Files changed: {diffs.length} · <span className="text-emerald-400">+{additions}</span> · <span className="text-rose-400">-{deletions}</span></p><p className="mt-2 text-slate-500">Base snapshot: {proposal.base_snapshot_hash || 'Unavailable'}</p></div>
            <div><p className="font-semibold text-slate-300">Impact</p><p className="mt-1 text-slate-400">Affected files: {String(impact.files_changed ?? impact.affected_files?.length ?? diffs.length)}</p><p className="mt-1 text-slate-400">Dependencies changed: {String(impact.dependencies_changed ?? 'Unknown')}</p><p className="mt-1 text-slate-400">Routes: {Array.isArray(impact.routes_affected) && impact.routes_affected.length ? impact.routes_affected.join(', ') : 'None identified'}</p><p className="mt-1 text-slate-400">Confidence: {String(impact.confidence ?? 'Unspecified')}</p><p className="mt-2 text-amber-300">Warnings: {warnings.join('; ') || impact.risks?.join('; ') || 'None'}</p></div>
          </div>
          {!['approved', 'applied', 'rejected'].includes(proposal.status) && !proposal.stale && <div className="space-y-2 border-t border-slate-800 pt-3"><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Feedback for a revision (required for revision requests)" className="w-full rounded border border-slate-700 bg-slate-900 p-2 text-xs text-slate-200" /><div className="flex flex-wrap gap-2"><button type="button" disabled={busy || !feedback.trim()} onClick={() => void action('revision')} className="rounded bg-amber-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">Request Revision</button><button type="button" disabled={busy} onClick={() => void action('reject')} className="inline-flex items-center gap-1 rounded bg-rose-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><XCircle className="h-3.5 w-3.5" />Reject Changes</button><button type="button" disabled={busy} onClick={() => void action('approve')} className="inline-flex items-center gap-1 rounded bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}<CheckCircle2 className="h-3.5 w-3.5" />Approve Changes</button></div>{actionLabel && <p className="text-xs text-slate-500">{actionLabel}</p>}</div>}
        </>
      )}
    </section>
  );
}
