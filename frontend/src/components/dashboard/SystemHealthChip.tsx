'use client';

import { useCallback, useEffect, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { apiClient, type FullHealth } from '@/lib/api';
import { StatusDot } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';

export function SystemHealthChip() {
  const [open, setOpen] = useState(false);
  const [health, setHealth] = useState<FullHealth | null>(null);
  const [sandbox, setSandbox] = useState<{ status: string; configured: boolean } | null>(null);
  const [storage, setStorage] = useState<{ status: string; configured: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [full, box, store] = await Promise.all([
        apiClient.getFullHealth(),
        apiClient.getSandboxHealth().catch(() => null),
        apiClient.getStorageHealth().catch(() => null),
      ]);
      setHealth(full);
      setSandbox(box);
      setStorage(store);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unreachable');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const happy = !error && health?.status === 'ok';

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-2 rounded-[10px] bg-paper/10 px-3 py-1.5 text-xs text-cream/80 hover:bg-paper/15"
      >
        <StatusDot tone={happy ? 'good' : 'warn'} />
        {happy ? 'Ready' : error ? 'Unreachable' : 'Checking'}
        <ChevronDown className={cn('h-3.5 w-3.5 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-20 w-64 space-y-2 rounded-rlb glass-dark p-4 text-xs text-cream/80 shadow-float">
          <Row label="FastAPI" ok={!error} detail={error || health?.environment || 'ok'} />
          <Row label="Database" ok={Boolean(health?.database?.connected)} detail={health?.database?.message || '—'} />
          <Row label="Sandbox" ok={sandbox?.configured} detail={sandbox?.status || 'unset'} />
          <Row label="Storage" ok={storage?.configured} detail={storage?.status || 'unset'} />
        </div>
      )}
    </div>
  );
}

function Row({ label, ok, detail }: { label: string; ok?: boolean; detail: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="inline-flex items-center gap-2">
        <StatusDot tone={ok ? 'good' : 'warn'} />
        {label}
      </span>
      <span className="max-w-[140px] truncate text-cream/50">{detail}</span>
    </div>
  );
}
