'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertCircle, ArrowLeft, GitBranch, Loader2, MonitorUp, Upload, X } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { apiClient } from '@/lib/api';
import { entriesFromFileList, sanitizeImportEntries, validateImportPayload, validateZipFile, type ImportEntry } from '@/lib/importFiles';
import { WorldScene } from '@/components/world/WorldScene';
import { Input, Textarea } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';

type Source = 'zip' | 'template' | 'empty';
type ImportKind = 'archive' | 'git' | 'device';

const TEMPLATES = [
  { id: 'next', name: 'Next.js', stack: 'App Router · TypeScript', nameHint: 'next-garden', note: 'A quiet Next.js starter to grow from.' },
  { id: 'python', name: 'Python API', stack: 'FastAPI', nameHint: 'python-meadow', note: 'A small API garden to iterate in.' },
  { id: 'ai', name: 'AI App', stack: 'TypeScript · agents', nameHint: 'ai-workshop', note: 'A workspace shaped for model-backed features.' },
  { id: 'react', name: 'React', stack: 'Vite · React', nameHint: 'react-hillside', note: 'A client app with room to wander.' },
  { id: 'blank', name: 'Blank', stack: 'Empty canvas', nameHint: 'blank-island', note: 'Start from zero.' },
];

export default function NewWorkspacePage() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [environmentMode, setEnvironmentMode] = useState<'sandboxed' | 'connected'>('sandboxed');
  const [projectSource, setProjectSource] = useState<Source>('empty');
  const [importKind, setImportKind] = useState<ImportKind>('archive');
  const [gitUrl, setGitUrl] = useState('');
  const [templateId, setTemplateId] = useState('next');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [deviceEntries, setDeviceEntries] = useState<ImportEntry[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated, router]);

  const takeFile = (file?: File) => {
    if (!file) return;
    const zipError = validateZipFile(file);
    if (zipError) {
      setError(zipError);
      setSelectedFile(null);
      return;
    }
    setError(null);
    setSelectedFile(file);
    setProjectSource('zip');
    setImportKind('archive');
  };

  const takeDeviceFiles = (list: FileList | File[]) => {
    const { entries } = sanitizeImportEntries(entriesFromFileList(list));
    const payloadError = validateImportPayload(entries);
    if (payloadError) {
      setError(payloadError);
      setDeviceEntries([]);
      return;
    }
    setError(null);
    setDeviceEntries(entries);
    setProjectSource('zip');
    setImportKind('device');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError('Workspace name is required.');
      return;
    }
    if (projectSource === 'zip' && importKind === 'archive' && !selectedFile) {
      setError('Drop a .zip archive, or choose Empty / Template.');
      return;
    }
    if (projectSource === 'zip' && importKind === 'device' && deviceEntries.length === 0) {
      setError('Choose files or a folder to import, or switch to Empty.');
      return;
    }
    setIsSubmitting(true);
    try {
      const formData = new FormData();
      formData.append('name', name.trim());
      if (description.trim()) formData.append('description', description.trim());
      formData.append('environment_mode', environmentMode);
      if (projectSource === 'zip' && importKind === 'archive' && selectedFile) {
        formData.append('file', selectedFile);
      }
      const created = await apiClient.createWorkspace(formData, user?.id);
      if (projectSource === 'zip' && importKind === 'device' && deviceEntries.length > 0) {
        await apiClient.importWorkspaceFiles(created.id, deviceEntries, user?.id);
      }
      router.push(`/dashboard/workspaces/${created.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to provision workspace');
      setIsSubmitting(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gold" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm text-cream/60 hover:text-cream">
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>

      <div className="relative overflow-hidden rounded-[22px] border border-cream/10">
        <div className="absolute inset-0 opacity-55"><WorldScene time="day" compact /></div>
        <div className="relative z-10 bg-gradient-to-r from-[#0e1a28]/80 via-[#0e1a28]/40 to-transparent px-6 py-8 sm:px-8">
          <h1 className="max-w-xl text-3xl font-semibold tracking-tight text-cream sm:text-4xl">Let’s make a place for it.</h1>
          <p className="mt-2 max-w-lg text-[15px] text-cream/70">Bring your project, start from a template, or begin with an idea.</p>
        </div>
      </div>

      {error && (
        <div className="flex gap-2 rounded-[14px] bg-coral/15 p-3 text-sm text-coral">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid gap-3 md:grid-cols-3">
          <Choice title="Import" body="ZIP, files, or a git URL note" active={projectSource === 'zip'} onClick={() => setProjectSource('zip')} />
          <Choice
            title="Template"
            body="Visually rich starters"
            active={projectSource === 'template'}
            onClick={() => {
              setProjectSource('template');
              setSelectedFile(null);
              const tpl = TEMPLATES.find((item) => item.id === templateId) || TEMPLATES[0];
              setName(tpl.nameHint);
              setDescription(tpl.note);
            }}
          />
          <Choice
            title="Empty"
            body="Start from zero"
            active={projectSource === 'empty'}
            onClick={() => {
              setProjectSource('empty');
              setSelectedFile(null);
            }}
          />
        </div>

        {projectSource === 'zip' && (
          <div className="surface space-y-4 rounded-[18px] p-5">
            <div className="flex flex-wrap gap-2">
              <ImportChip icon={Upload} label="Archive" active={importKind === 'archive'} onClick={() => setImportKind('archive')} />
              <ImportChip icon={GitBranch} label="Git Repository" active={importKind === 'git'} onClick={() => setImportKind('git')} />
              <ImportChip icon={MonitorUp} label="Upload from Device" active={importKind === 'device'} onClick={() => setImportKind('device')} />
            </div>

            {importKind === 'git' ? (
              <div>
                <label className="block text-xs text-cream/60">
                  Repository URL
                  <Input
                    className="mt-1.5 bg-paper"
                    value={gitUrl}
                    onChange={(e) => setGitUrl(e.target.value)}
                    placeholder="https://github.com/you/project.git"
                  />
                </label>
                <p className="mt-2 text-xs text-cream/45">
                  Git clone is not part of the current create contract. RLB will open an empty workspace — import a ZIP of the repo to bring files in.
                </p>
              </div>
            ) : importKind === 'device' ? (
              <div className="space-y-3">
                <p className="text-sm text-cream/70">Import loose files or a folder into a new empty workspace (same 100 MB / 5,000 file contract as the IDE).</p>
                {deviceEntries.length > 0 ? (
                  <div className="rounded-[12px] bg-paper/10 px-4 py-3 text-left">
                    <p className="font-medium text-cream">{deviceEntries.length} files selected</p>
                    <p className="text-xs text-cream/50 truncate">{deviceEntries.slice(0, 3).map((entry) => entry.relativePath).join(', ')}</p>
                    <button type="button" onClick={() => setDeviceEntries([])} className="mt-2 text-xs text-coral">Clear</button>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    <label className="inline-flex cursor-pointer rounded-[12px] bg-paper px-5 py-2 text-sm font-semibold text-ink">
                      Choose files
                      <input type="file" multiple className="sr-only" onChange={(e) => takeDeviceFiles(e.target.files || [])} />
                    </label>
                    <label className="inline-flex cursor-pointer rounded-[12px] border border-cream/20 px-5 py-2 text-sm font-semibold text-cream">
                      Choose folder
                      <input
                        type="file"
                        multiple
                        className="sr-only"
                        // @ts-expect-error webkitdirectory is supported in Chromium
                        webkitdirectory=""
                        onChange={(e) => takeDeviceFiles(e.target.files || [])}
                      />
                    </label>
                  </div>
                )}
              </div>
            ) : (
              <div
                className={cn(
                  'rounded-[16px] border-2 border-dashed p-8 text-center transition',
                  dragOver ? 'border-gold bg-gold/10' : 'border-cream/20 bg-[#0b1622]/60',
                )}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  takeFile(e.dataTransfer.files[0]);
                }}
              >
                {selectedFile ? (
                  <div className="flex items-center justify-between rounded-[12px] bg-paper/10 px-4 py-3 text-left">
                    <div>
                      <p className="font-medium text-cream">{selectedFile.name}</p>
                      <p className="text-xs text-cream/50">{(selectedFile.size / 1024).toFixed(1)} KB · 25 MB max · ZIP only</p>
                    </div>
                    <button type="button" onClick={() => setSelectedFile(null)} className="text-cream/50 hover:text-coral" aria-label="Remove archive">
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ) : (
                  <>
                    <Upload className="mx-auto h-8 w-8 text-gold" />
                    <p className="mt-3 text-lg font-semibold text-cream">Drop a ZIP here</p>
                    <p className="mt-1 text-sm text-cream/55">.zip only · up to 25 MB. tar/git clone are not supported yet.</p>
                    <label className="mt-5 inline-flex cursor-pointer rounded-[12px] bg-paper px-5 py-2 text-sm font-semibold text-ink">
                      Choose ZIP
                      <input type="file" accept=".zip,application/zip" className="sr-only" onChange={(e) => takeFile(e.target.files?.[0])} />
                    </label>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {projectSource === 'template' && (
          <div className="space-y-3">
            <p className="text-xs text-cream/50">
              Templates currently prefill a name and note. The backend still provisions an empty workspace — import a ZIP afterward if you need starter files.
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {TEMPLATES.map((tpl, index) => (
              <button
                key={tpl.id}
                type="button"
                onClick={() => {
                  setTemplateId(tpl.id);
                  setName(tpl.nameHint);
                  setDescription(tpl.note);
                }}
                className={cn(
                  'overflow-hidden rounded-[16px] border text-left transition hover-lift',
                  templateId === tpl.id ? 'border-coral/50 bg-coral/10' : 'border-cream/10 bg-[#0b1622]/70',
                )}
              >
                <div className="relative h-16">
                  <WorldScene time={index % 2 === 0 ? 'day' : 'sunset'} compact showCabin={false} />
                </div>
                <div className="p-3">
                  <p className="text-sm font-semibold text-cream">{tpl.name}</p>
                  <p className="mt-0.5 text-[11px] text-cream/50">{tpl.stack}</p>
                </div>
              </button>
            ))}
            </div>
          </div>
        )}

        <div className="surface space-y-4 rounded-[18px] p-5">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block text-xs text-cream/60">
              Workspace name
              <Input className="mt-1.5 bg-paper" value={name} onChange={(e) => setName(e.target.value)} placeholder="meadow-checkout" required disabled={isSubmitting} />
            </label>
            <label className="block text-xs text-cream/60">
              Environment
              <select
                value={environmentMode}
                onChange={(e) => setEnvironmentMode(e.target.value as 'sandboxed' | 'connected')}
                className="mt-1.5 w-full rounded-[12px] border border-midnight/10 bg-paper px-3.5 py-2.5 text-[15px] text-ink"
              >
                <option value="sandboxed">Sandboxed</option>
                <option value="connected">Connected</option>
              </select>
            </label>
          </div>
          <label className="block text-xs text-cream/60">
            Optional note
            <Textarea className="mt-1.5 bg-paper" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Fix the authentication flow, then add tests for checkout." disabled={isSubmitting} />
          </label>
        </div>

        <div className="flex justify-end gap-3">
          <Link href="/dashboard" className="rounded-[12px] px-5 py-2.5 text-sm text-cream/70 hover:text-cream">Cancel</Link>
          <Button type="submit" disabled={isSubmitting} className="min-w-[180px]">
            {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Create workspace
          </Button>
        </div>
      </form>
    </div>
  );
}

function Choice({ title, body, active, onClick }: { title: string; body: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-[16px] border p-5 text-left transition hover-lift',
        active ? 'border-coral/50 bg-paper text-ink shadow-float' : 'border-cream/10 bg-[#0b1622]/70 text-cream hover:border-cream/20',
      )}
    >
      <p className="text-lg font-semibold">{title}</p>
      <p className={cn('mt-1 text-sm', active ? 'text-ink/60' : 'text-cream/55')}>{body}</p>
    </button>
  );
}

function ImportChip({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: typeof Upload;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-2 rounded-[10px] px-3 py-1.5 text-xs font-medium transition',
        active ? 'bg-coral/20 text-cream' : 'bg-paper/5 text-cream/60 hover:text-cream',
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
