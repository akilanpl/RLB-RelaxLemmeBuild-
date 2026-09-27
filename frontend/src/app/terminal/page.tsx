'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { apiClient } from '@/lib/api';
import { WorldScene } from '@/components/world/WorldScene';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { Button } from '@/components/ui/Button';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';

type DependencyHealth = { status: string; configured: boolean };

export default function SandboxPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [health, setHealth] = useState<DependencyHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated, router]);

  useEffect(() => {
    if (!isAuthenticated) return;
    apiClient.getSandboxHealth()
      .then(setHealth)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to reach sandbox health endpoint'));
  }, [isAuthenticated]);

  if (authLoading || !isAuthenticated) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gold" />
      </div>
    );
  }

  const healthy = health?.configured === true;
  const status = error ? 'unreachable' : !health ? 'provisioning' : healthy ? 'configured' : 'not_configured';

  return (
    <div className="relative overflow-hidden rounded-[22px] border border-cream/10">
      <div className="absolute inset-0 opacity-40">
        <WorldScene time="night" />
      </div>
      <div className="relative z-10 space-y-6 bg-gradient-to-b from-[#0c1c2e]/55 via-[#0c1c2e]/80 to-[#0c1c2e] p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-cream sm:text-4xl">Sandbox Runtime</h1>
            <p className="mt-1 text-sm text-cream/60">Isolated execution. Nothing runs on your host from this page.</p>
          </div>
          <StatusBadge status={status} className="text-sm px-3 py-1.5" />
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Info label="Runtime status" value={error ? 'Unreachable' : healthy ? 'Configured' : health?.status || 'Checking'} />
          <Info label="Workspace" value="Open from Workspaces" />
          <Info label="Driver" value="Daytona" />
          <Info label="Recent execution" value="Lives with the latest workspace task" />
        </div>

        <div className="surface rounded-[16px] p-5 text-sm text-cream/75">
          {!health && !error ? (
            <p className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin text-gold" /> Checking /health/sandbox…</p>
          ) : error ? (
            <p className="text-coral">{error}</p>
          ) : (
            <p>Configured · {health?.configured ? 'yes' : 'not configured'}</p>
          )}
        </div>

        <Button type="button" onClick={() => router.push('/dashboard/workspaces')}>
          Open workspace
        </Button>
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface rounded-[14px] p-4">
      <p className="text-[11px] tracking-wide text-cream/40">{label}</p>
      <p className="mt-1 text-sm font-medium text-cream">{value}</p>
    </div>
  );
}
