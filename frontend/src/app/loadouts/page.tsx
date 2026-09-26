'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { KeyRound, Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { apiClient } from '@/lib/api';
import { AGENT_ROLES } from '@/lib/agents';
import { AgentFigure } from '@/components/world/AgentFigure';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { Toast } from '@/components/ui/Toast';

type Credential = {
  id: string;
  provider_id: string;
  provider_name?: string;
  product_label?: string;
  key_fingerprint: string;
};

type WorkerConfig = {
  id: string;
  provider_id: string;
  provider_name?: string;
  product_label?: string;
  model_name: string;
  credential_id?: string;
};

type LoadoutRecord = {
  id: string;
  name: string;
  mappings: Record<string, { primary_worker_id: string; fallback_worker_ids?: string[] }>;
};

const LLM_ROLES = [
  { id: 'planner', label: 'Planner' },
  { id: 'coder', label: 'Coder' },
  { id: 'test_architect', label: 'Test Architect' },
  { id: 'reviewer', label: 'Reviewer' },
] as const;

const SHOWCASE_PROVIDERS = [
  { id: 'google', name: 'Google Gemini', match: ['google', 'gemini'] },
  { id: 'openai', name: 'OpenAI', match: ['openai'] },
  { id: 'anthropic', name: 'Anthropic', match: ['anthropic', 'claude'] },
  { id: 'groq', name: 'Groq', match: ['groq'] },
];

function optionLabel(worker: WorkerConfig): string {
  const provider = worker.provider_name || worker.provider_id;
  const credential = worker.provider_name || worker.product_label || provider;
  return `${worker.model_name} · ${credential}`;
}

function matchesProvider(credential: Credential, match: string[]) {
  const hay = `${credential.provider_id} ${credential.provider_name || ''}`.toLowerCase();
  return match.some((token) => hay.includes(token));
}

export default function LoadoutsPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [workers, setWorkers] = useState<WorkerConfig[]>([]);
  const [loadouts, setLoadouts] = useState<LoadoutRecord[]>([]);
  const [activeLoadoutId, setActiveLoadoutId] = useState('');
  const [loadoutName, setLoadoutName] = useState('Default RLB Loadout');
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [showCredentialForm, setShowCredentialForm] = useState(false);
  const [showModelForm, setShowModelForm] = useState(false);
  const [providerName, setProviderName] = useState('');
  const [credentialLabel, setCredentialLabel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [modelCredentialId, setModelCredentialId] = useState('');
  const [modelName, setModelName] = useState('');
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    const [nextCredentials, nextWorkers, nextLoadouts] = await Promise.all([
      apiClient.listProviderCredentials(),
      apiClient.listWorkers(),
      apiClient.listLoadouts(),
    ]);
    setCredentials(nextCredentials);
    setWorkers(nextWorkers);
    setLoadouts(nextLoadouts);
    const current = nextLoadouts.find((item) => item.id === activeLoadoutId) || nextLoadouts[0];
    if (current) {
      setActiveLoadoutId(current.id);
      setLoadoutName(current.name || 'Default RLB Loadout');
      const nextAssignments: Record<string, string> = {};
      for (const role of LLM_ROLES) {
        const workerId = current.mappings?.[role.id]?.primary_worker_id;
        if (workerId && nextWorkers.some((worker) => worker.id === workerId)) {
          nextAssignments[role.id] = workerId;
        }
      }
      setAssignments(nextAssignments);
    }
  }, [activeLoadoutId]);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated, router]);

  useEffect(() => {
    if (!isAuthenticated) return;
    refresh().catch(() => {
      setCredentials([]);
      setWorkers([]);
      setLoadouts([]);
      setError('Unable to load AI configuration.');
    });
  }, [isAuthenticated, refresh]);

  const workerOptions = useMemo(() => workers, [workers]);

  const extraCredentials = credentials.filter(
    (credential) => !SHOWCASE_PROVIDERS.some((provider) => matchesProvider(credential, provider.match)),
  );

  async function saveCredential(event: FormEvent) {
    event.preventDefault();
    setError('');
    try {
      await apiClient.saveProviderCredential(providerName.trim(), apiKey, {
        label: credentialLabel.trim() || undefined,
        baseUrl: baseUrl.trim() || undefined,
      });
      setApiKey('');
      setProviderName('');
      setCredentialLabel('');
      setBaseUrl('');
      setShowCredentialForm(false);
      setMessage('Credential saved securely. The key is never displayed.');
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Credential could not be saved.');
    }
  }

  async function saveModel(event: FormEvent) {
    event.preventDefault();
    setError('');
    const credential = credentials.find((item) => item.id === modelCredentialId);
    if (!credential) {
      setError('Select a stored credential.');
      return;
    }
    try {
      await apiClient.saveWorker({
        credential_id: credential.id,
        provider_id: credential.provider_id,
        model_name: modelName.trim(),
      });
      setModelName('');
      setShowModelForm(false);
      setMessage('Model configuration saved. It can be assigned to any agent role.');
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Model configuration could not be saved.');
    }
  }

  async function saveLoadout() {
    setSaving(true);
    setError('');
    try {
      const mappings: Record<string, { primary_worker_id: string; fallback_worker_ids?: string[] }> = {};
      for (const role of LLM_ROLES) {
        const workerId = assignments[role.id];
        if (workerId) mappings[role.id] = { primary_worker_id: workerId, fallback_worker_ids: [] };
      }
      const saved = await apiClient.saveLoadout({
        id: activeLoadoutId || undefined,
        name: loadoutName.trim() || 'Default RLB Loadout',
        mappings,
      });
      setActiveLoadoutId(saved.id);
      setMessage('Loadout saved. Assignments persist after refresh.');
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Loadout could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  async function removeCredential(providerId: string) {
    setError('');
    try {
      await apiClient.deleteProviderCredential(providerId);
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Credential could not be removed.');
    }
  }

  if (authLoading || !isAuthenticated) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gold" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-cream sm:text-4xl">How your RLB team thinks.</h1>
        <p className="mt-2 text-[15px] text-cream/65">Give each role the model that fits it best.</p>
      </div>

      <Toast message={error || message} tone={error ? 'error' : 'ok'} />

      <section className="surface rounded-[18px] p-5">
        <p className="text-sm font-semibold text-cream">Same models. Different superpowers.</p>
        <p className="mt-1 text-sm text-cream/55">
          One credential can power every role. Planner, coder, and reviewer just use it differently.
        </p>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[11px] font-semibold tracking-[0.18em] text-cream/50">AI CREDENTIALS</h2>
          <Button type="button" onClick={() => setShowCredentialForm((open) => !open)} className="px-3 py-2 text-xs">
            <Plus className="h-4 w-4" /> Add API Key
          </Button>
        </div>
        {showCredentialForm && (
          <form onSubmit={saveCredential} className="space-y-3 rounded-[16px] bg-paper p-5">
            <label className="block text-xs text-ink/70">Provider
              <Input className="mt-1.5" value={providerName} onChange={(e) => setProviderName(e.target.value)} placeholder="Google Gemini" required autoComplete="off" />
            </label>
            <label className="block text-xs text-ink/70">Label
              <Input className="mt-1.5" value={credentialLabel} onChange={(e) => setCredentialLabel(e.target.value)} placeholder="Gemini Personal" autoComplete="off" />
            </label>
            <label className="block text-xs text-ink/70">API key
              <Input className="mt-1.5" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="API key" required autoComplete="new-password" />
            </label>
            <label className="block text-xs text-ink/70">Optional base URL
              <Input className="mt-1.5" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="Optional base URL" autoComplete="off" />
            </label>
            <Button type="submit">Save encrypted credential</Button>
          </form>
        )}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {SHOWCASE_PROVIDERS.map((provider) => {
            const match = credentials.find((credential) => matchesProvider(credential, provider.match));
            return (
              <div key={provider.id} className="surface hover-lift rounded-[16px] p-4">
                <p className="font-semibold text-cream">{provider.name}</p>
                <div className="mt-3">
                  <StatusBadge status={match ? 'configured' : 'not_configured'} />
                </div>
                {match ? (
                  <div className="mt-3 flex items-start justify-between gap-2">
                    <p className="text-[11px] text-cream/40">Fingerprint · {match.key_fingerprint}</p>
                    <button type="button" onClick={() => removeCredential(match.provider_id)} className="text-cream/35 hover:text-coral" aria-label={`Remove ${provider.name} credential`}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ) : (
                  <p className="mt-3 text-xs text-cream/40">Add a key to enable this provider.</p>
                )}
              </div>
            );
          })}
          {extraCredentials.map((credential) => (
            <div key={credential.id} className="surface rounded-[16px] p-4">
              <p className="font-semibold text-cream">{credential.provider_name || credential.provider_id}</p>
              <div className="mt-3"><StatusBadge status="configured" /></div>
              <div className="mt-3 flex items-start justify-between">
                <p className="text-[11px] text-cream/40">Fingerprint · {credential.key_fingerprint}</p>
                <button type="button" onClick={() => removeCredential(credential.provider_id)} className="text-cream/35 hover:text-coral" aria-label="Remove credential">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
        {credentials.length === 0 && (
          <p className="flex items-center gap-2 text-sm text-cream/50">
            <KeyRound className="h-4 w-4 text-gold" /> Keys are stored encrypted and never shown again.
          </p>
        )}
      </section>

      <section className="space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-[11px] font-semibold tracking-[0.18em] text-cream/50">AGENT ROLES</h2>
          <button type="button" onClick={() => setShowModelForm((open) => !open)} className="text-sm text-gold hover:underline">
            Add model
          </button>
        </div>
        {showModelForm && (
          <form onSubmit={saveModel} className="grid gap-3 rounded-[16px] bg-paper p-5 sm:grid-cols-2">
            <Select value={modelCredentialId} onChange={(e) => setModelCredentialId(e.target.value)} required>
              <option value="">Select credential</option>
              {credentials.map((credential) => (
                <option key={credential.id} value={credential.id}>{credential.provider_name || credential.provider_id}</option>
              ))}
            </Select>
            <Input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="gemini-2.5-flash" required />
            <div className="sm:col-span-2"><Button type="submit">Save model configuration</Button></div>
          </form>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Select
            value={activeLoadoutId}
            onChange={(e) => {
              const next = loadouts.find((item) => item.id === e.target.value);
              setActiveLoadoutId(e.target.value);
              if (!next) return;
              setLoadoutName(next.name);
              const nextAssignments: Record<string, string> = {};
              for (const role of LLM_ROLES) {
                const workerId = next.mappings?.[role.id]?.primary_worker_id;
                if (workerId && workers.some((worker) => worker.id === workerId)) nextAssignments[role.id] = workerId;
              }
              setAssignments(nextAssignments);
            }}
            className="sm:max-w-xs"
          >
            {loadouts.length === 0 && <option value="">Default RLB Loadout</option>}
            {loadouts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>
          <Input value={loadoutName} onChange={(e) => setLoadoutName(e.target.value)} />
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {AGENT_ROLES.map((role) => {
            const isExecutor = role.id === 'test_executor';
            const worker = workers.find((item) => item.id === assignments[role.id]);
            return (
              <div key={role.id} className="surface hover-lift flex gap-3 rounded-[16px] p-4">
                <AgentFigure roleId={role.id} size={52} />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-cream">{role.name}</p>
                  <p className="mt-1 text-xs text-cream/50">{role.description}</p>
                  {isExecutor ? (
                    <p className="mt-3 text-xs text-cream/45">Sandbox Runtime · no LLM credential</p>
                  ) : (
                    <Select
                      className="mt-3 bg-paper"
                      aria-label={`${role.name} model`}
                      value={assignments[role.id] || ''}
                      onChange={(e) => setAssignments((current) => ({ ...current, [role.id]: e.target.value }))}
                    >
                      <option value="">{workerOptions.length ? 'Select model configuration' : 'No model configurations yet'}</option>
                      {workerOptions.map((item) => (
                        <option key={`${role.id}-${item.id}`} value={item.id}>{optionLabel(item)}</option>
                      ))}
                    </Select>
                  )}
                  <div className="mt-3">
                    <StatusBadge status={isExecutor || worker ? 'ready' : 'not_configured'} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <Button type="button" onClick={saveLoadout} disabled={saving}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
          Save Loadout
        </Button>
      </section>
    </div>
  );
}
