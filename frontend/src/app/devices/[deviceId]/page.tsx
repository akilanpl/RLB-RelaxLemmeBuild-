'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  Activity,
  ArrowLeft,
  Check,
  Clock3,
  Download,
  Loader2,
  Play,
  RefreshCw,
  RotateCw,
  Square,
  Terminal,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import type { Workspace } from '@/types/workspace';
import {
  apiClient,
  ApiError,
  type DeviceCommand,
  type DeviceCommandType,
  type DeviceEvent,
  type DeviceTaskArtifact,
  type RemoteDevice,
} from '@/lib/api';
import { Button } from '@/components/ui/Button';

const ACTIVE_COMMAND_STATES = new Set(['queued', 'pending', 'running', 'accepted', 'dispatched', 'delivered', 'acknowledged', 'executing']);

function onlineStatus(device: RemoteDevice): boolean {
  if (typeof device.online === 'boolean') return device.online;
  if (typeof device.is_online === 'boolean') return device.is_online;
  return ['online', 'connected', 'ready'].includes(String(device.status ?? '').toLowerCase());
}

function connectionLabel(device: RemoteDevice): string {
  const status = String(device.status ?? '').toUpperCase();
  if (status === 'RECONNECTING') return 'Reconnecting';
  if (status === 'REVOKED') return 'Revoked';
  if (status === 'OFFLINE') return 'Offline';
  return onlineStatus(device) ? 'Online' : 'Offline';
}

function valueText(value: unknown): string {
  if (value == null || value === '') return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value, null, 2);
}

function recordValue(record: Record<string, unknown> | null | undefined, ...keys: string[]): unknown {
  for (const key of keys) {
    if (record?.[key] != null) return record[key];
  }
  return undefined;
}

function formatTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function commandStatus(command: DeviceCommand): string {
  return String(command.status || 'unknown').toLowerCase();
}

function statusStyle(status: string): string {
  if (['succeeded', 'success', 'completed', 'complete', 'done'].includes(status)) return 'bg-meadow/15 text-meadow';
  if (['failed', 'error', 'cancelled', 'rejected'].includes(status)) return 'bg-coral/15 text-coral';
  if (ACTIVE_COMMAND_STATES.has(status)) return 'bg-gold/15 text-gold';
  return 'bg-cream/10 text-cream/60';
}

export default function DeviceDetailPage() {
  const params = useParams<{ deviceId: string }>();
  const deviceId = Array.isArray(params.deviceId) ? params.deviceId[0] : params.deviceId;
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [device, setDevice] = useState<RemoteDevice | null>(null);
  const [commands, setCommands] = useState<DeviceCommand[]>([]);
  const [events, setEvents] = useState<DeviceEvent[]>([]);
  const [artifacts, setArtifacts] = useState<DeviceTaskArtifact[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [eventsMessage, setEventsMessage] = useState<string | null>(null);
  const [artifactMessage, setArtifactMessage] = useState<string | null>(null);
  const eventCursor = useRef<string | null>(null);
  const requestGeneration = useRef(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sending, setSending] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [customCommand, setCustomCommand] = useState<DeviceCommandType>('PROMPT');
  const [promptText, setPromptText] = useState('');
  const [artifactPath, setArtifactPath] = useState('');
  const [selectedArtifactTaskId, setSelectedArtifactTaskId] = useState('');
  const [startWorkspaceId, setStartWorkspaceId] = useState('');
  const [startTitle, setStartTitle] = useState('');
  const [startObjective, setStartObjective] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated, router]);

  useEffect(() => {
    requestGeneration.current += 1;
    eventCursor.current = null;
    setDevice(null);
    setCommands([]);
    setEvents([]);
    setArtifacts([]);
    setSelectedArtifactTaskId('');
    setLoading(true);
  }, [deviceId]);

  const loadDeviceData = useCallback(async (isRefresh = false) => {
    if (!deviceId) return;
    const generation = requestGeneration.current;
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    try {
      const [nextDevice, nextCommands] = await Promise.all([
        apiClient.getDevice(deviceId),
        apiClient.listDeviceCommands(deviceId),
      ]);
      if (generation !== requestGeneration.current) return;
      setDevice(nextDevice);
      setCommands(nextCommands);
      try {
        const page = await apiClient.listDeviceEvents(deviceId, eventCursor.current);
        if (generation !== requestGeneration.current) return;
        setEvents((current) => {
          const known = new Set(current.map((event) => event.id));
          return [...current, ...page.events.filter((event) => !known.has(event.id))].slice(-100);
        });
        eventCursor.current = page.cursor;
        setEventsMessage(null);
      } catch (eventsErr) {
        if (generation !== requestGeneration.current) return;
        setEventsMessage(
          eventsErr instanceof ApiError && eventsErr.status === 404
            ? 'Device events are not available yet.'
            : `Could not load events: ${eventsErr instanceof Error ? eventsErr.message : 'Unknown error'}`,
        );
      }
      setError(null);
    } catch (err) {
      if (generation === requestGeneration.current) {
        setError(err instanceof Error ? err.message : 'Could not load device details.');
      }
    } finally {
      if (generation === requestGeneration.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [deviceId]);

  useEffect(() => {
    if (isAuthenticated) void loadDeviceData();
  }, [isAuthenticated, loadDeviceData]);

  useEffect(() => {
    if (!isAuthenticated) return;
    void apiClient.listWorkspaces().then(setWorkspaces).catch((err: unknown) => {
      setCommandError(err instanceof Error ? err.message : 'Could not load workspaces.');
    });
  }, [isAuthenticated]);

  const hasActiveCommand = useMemo(
    () => commands.some((command) => ACTIVE_COMMAND_STATES.has(commandStatus(command))),
    [commands],
  );

  const artifactTaskOptions = useMemo(() => {
    const ids = new Set<string>();
    if (typeof device?.current_task_id === 'string') ids.add(device.current_task_id);
    for (const event of [...events].reverse()) {
      if (typeof event.task_id === 'string') ids.add(event.task_id);
    }
    if (selectedArtifactTaskId) ids.add(selectedArtifactTaskId);
    return [...ids];
  }, [device?.current_task_id, events, selectedArtifactTaskId]);

  useEffect(() => {
    if (selectedArtifactTaskId || !artifactTaskOptions.length) return;
    const activeTaskId = typeof device?.current_task_id === 'string' ? device.current_task_id : null;
    setSelectedArtifactTaskId(activeTaskId ?? artifactTaskOptions[0]);
  }, [artifactTaskOptions, device?.current_task_id, selectedArtifactTaskId]);

  useEffect(() => {
    if (!deviceId || !selectedArtifactTaskId) {
      setArtifacts([]);
      setArtifactMessage(null);
      return;
    }
    let cancelled = false;
    setArtifacts([]);
    apiClient.listDeviceTaskArtifacts(deviceId, selectedArtifactTaskId)
      .then((nextArtifacts) => {
        if (cancelled) return;
        setArtifacts(nextArtifacts);
        setArtifactMessage(null);
      })
      .catch((artifactErr: unknown) => {
        if (cancelled) return;
        setArtifactMessage(artifactErr instanceof Error ? artifactErr.message : 'Could not load task artifacts.');
      });
    return () => { cancelled = true; };
  }, [deviceId, selectedArtifactTaskId]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const timer = window.setInterval(() => void loadDeviceData(true), hasActiveCommand ? 4000 : 15000);
    return () => window.clearInterval(timer);
  }, [hasActiveCommand, isAuthenticated, loadDeviceData]);

  async function runCommand(commandType: DeviceCommandType, payload?: Record<string, unknown>, taskId?: string) {
    if (sending) return;
    setSending(commandType);
    setCommandError(null);
    try {
      await apiClient.sendDeviceCommand(deviceId, commandType, payload, {
        task_id: taskId ?? (typeof device?.current_task_id === 'string' ? device.current_task_id : undefined),
      });
      if (commandType === 'PROMPT') setPromptText('');
      await loadDeviceData(true);
    } catch (err) {
      setCommandError(err instanceof Error ? err.message : 'Could not send command.');
    } finally {
      setSending(null);
    }
  }

  async function revokeDevice() {
    if (!window.confirm(`Revoke access for “${device?.name ?? 'this device'}”? This device will no longer be able to connect.`)) return;
    setRevoking(true);
    setError(null);
    try {
      await apiClient.deleteDevice(deviceId);
      router.push('/devices');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revoke this device.');
      setRevoking(false);
    }
  }

  async function downloadArtifact(artifact: DeviceTaskArtifact) {
    try {
      const blob = await apiClient.downloadDeviceTaskArtifact(deviceId, artifact.task_id, artifact.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = artifact.name;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setCommandError(err instanceof Error ? err.message : 'Could not download artifact.');
    }
  }

  if (authLoading || !isAuthenticated || loading) {
    return <div className="flex min-h-[40vh] items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-gold" /></div>;
  }

  if (error && !device) {
    return (
      <div className="space-y-4">
        <Link href="/devices" className="inline-flex items-center gap-2 text-sm text-cream/60 hover:text-cream"><ArrowLeft className="h-4 w-4" /> Devices</Link>
        <p role="alert" className="rounded-xl border border-coral/20 bg-coral/10 px-4 py-3 text-sm text-coral">{error}</p>
        <Button type="button" variant="secondary" onClick={() => void loadDeviceData()}><RefreshCw className="h-4 w-4" /> Try again</Button>
      </div>
    );
  }

  if (!device) return null;
  const online = onlineStatus(device);
  const runtime = device.runtime ?? (device.runtime_info as Record<string, unknown> | undefined) ?? null;
  const task = device.current_task ?? device.task ?? (device.active_task as Record<string, unknown> | undefined) ?? null;
  const runtimeStatus = recordValue(runtime, 'status', 'state') ?? device.runtime_state ?? device.runtime_status;
  const taskTitle = recordValue(task, 'title', 'name', 'objective') ?? device.task_title;
  const taskStatus = recordValue(task, 'status', 'state') ?? device.task_status ?? device.current_task_id;
  const currentTaskEvent = events
    .filter((event) => event.task_id === device.current_task_id)
    .sort((left, right) => Number(right.sequence ?? 0) - Number(left.sequence ?? 0))[0];
  const eventPayload = currentTaskEvent?.payload && typeof currentTaskEvent.payload === 'object'
    ? currentTaskEvent.payload as Record<string, unknown>
    : null;
  const currentAgent = recordValue(eventPayload, 'current_agent', 'agent', 'agent_role');

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/devices" className="inline-flex items-center gap-2 text-sm text-cream/60 hover:text-cream"><ArrowLeft className="h-4 w-4" /> All devices</Link>
        <div className="flex items-center gap-2">
          <Button type="button" variant="secondary" onClick={() => void loadDeviceData(true)} disabled={refreshing || revoking}>
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Button type="button" variant="danger" onClick={() => void revokeDevice()} disabled={revoking}>
            {revoking ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />} Revoke device
          </Button>
        </div>
      </div>

      {error && <p role="alert" className="rounded-xl border border-coral/20 bg-coral/10 px-4 py-3 text-sm text-coral">{error}</p>}

      <section className="surface rounded-[18px] p-5 sm:p-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div className="flex min-w-0 items-center gap-4">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[15px] bg-sky/10 text-sky"><Terminal className="h-6 w-6" /></span>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold tracking-[0.16em] text-cream/40">REMOTE DEVICE</p>
              <h1 className="truncate text-2xl font-semibold tracking-tight text-cream">{device.name}</h1>
              <p className="mt-0.5 truncate font-mono text-xs text-cream/40">{device.id}</p>
            </div>
          </div>
          <span className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${online ? 'bg-meadow/15 text-meadow' : 'bg-cream/10 text-cream/55'}`}>
            {online ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />} {connectionLabel(device)}
          </span>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <InfoTile label="Connection" value={valueText(device.status ?? (online ? 'Connected' : 'Disconnected'))} />
          <InfoTile label="Last seen" value={formatTime(device.last_seen_at ?? device.last_seen)} />
          <InfoTile label="Platform" value={valueText(device.platform ?? device.operating_system ?? device.os)} />
          <InfoTile label="App version" value={valueText(device.app_version ?? device.version ?? device.agent_version)} />
          <InfoTile label="Runtime version" value={valueText(device.runtime_version)} />
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-5">
          <section className="surface rounded-[18px] p-5">
            <div className="mb-4 flex items-center gap-2">
              <Activity className="h-4 w-4 text-coral" />
              <h2 className="font-semibold text-cream">Runtime & task</h2>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <InfoTile label="Runtime status" value={valueText(runtimeStatus)} />
              <InfoTile label="Current task" value={valueText(taskTitle)} />
              <InfoTile label="Workflow state" value={valueText(
                recordValue(task, 'status', 'state')
                  ?? recordValue(eventPayload, 'workflow_state')
                  ?? (currentTaskEvent ? currentTaskEvent.event_type : taskStatus),
              )} />
              <InfoTile label="Current agent" value={valueText(currentAgent)} />
            </div>
            {runtime && (
              <details className="mt-4 rounded-xl border border-cream/10 bg-midnight/35 p-3">
                <summary className="cursor-pointer text-xs font-medium text-cream/60">Runtime details</summary>
                <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-words text-[11px] text-cream/55">{JSON.stringify(runtime, null, 2)}</pre>
              </details>
            )}
          </section>

          <section className="surface rounded-[18px] p-5">
            <div className="mb-1 flex items-center gap-2">
              <Play className="h-4 w-4 text-coral" />
              <h2 className="font-semibold text-cream">Device controls</h2>
            </div>
            <p className="mb-4 text-xs text-cream/50">Commands are queued for the device and their status updates automatically.</p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" onClick={() => void runCommand('PAUSE_TASK')} disabled={!online || sending !== null || !device.current_task_id}>
                {sending === 'PAUSE_TASK' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />} Pause
              </Button>
              <Button type="button" variant="secondary" onClick={() => void runCommand('RESUME_TASK')} disabled={!online || sending !== null || !device.current_task_id}>
                {sending === 'RESUME_TASK' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Resume
              </Button>
              <Button type="button" variant="secondary" onClick={() => void runCommand('STOP_TASK')} disabled={!online || sending !== null || !device.current_task_id}>
                {sending === 'STOP_TASK' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />} Stop
              </Button>
            </div>
            <form
              className="mt-4 flex flex-col gap-2 sm:flex-row"
              onSubmit={(event) => {
                event.preventDefault();
                void runCommand(
                  customCommand,
                  customCommand === 'PROMPT' ? { prompt: promptText.trim() } : undefined,
                  typeof device.current_task_id === 'string' ? device.current_task_id : undefined,
                );
              }}
            >
              <label className="sr-only" htmlFor="custom-device-command">Device command type</label>
              <select
                id="custom-device-command"
                value={customCommand}
                onChange={(event) => setCustomCommand(event.target.value as DeviceCommandType)}
                className="min-w-0 flex-1 rounded-[12px] border border-cream/15 bg-[#0c1c2e] px-3 py-2.5 text-sm text-cream focus:border-coral/60 focus:outline-none"
              >
                <option value="PROMPT">Send prompt</option>
              </select>
              {customCommand === 'PROMPT' && (
                <label className="sr-only" htmlFor="device-prompt">Prompt for device</label>
              )}
              {customCommand === 'PROMPT' && (
                <textarea
                  id="device-prompt"
                  value={promptText}
                  onChange={(event) => setPromptText(event.target.value)}
                  maxLength={4000}
                  rows={3}
                  placeholder="Write a prompt for the device…"
                  className="min-w-0 flex-1 resize-y rounded-[12px] border border-cream/15 bg-midnight/50 px-3 py-2.5 text-sm text-cream placeholder:text-cream/35 focus:border-coral/60 focus:outline-none"
                />
              )}
              <Button
                type="submit"
                variant="secondary"
                disabled={!online || sending !== null || (customCommand === 'PROMPT' && !promptText.trim())}
              >
                {sending === customCommand ? <Loader2 className="h-4 w-4 animate-spin" /> : <Terminal className="h-4 w-4" />} Send
              </Button>
            </form>
            <form
              className="mt-4 grid gap-2 border-t border-cream/10 pt-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!startWorkspaceId || !startObjective.trim()) return;
                void runCommand('START_TASK', {
                  workspace_id: startWorkspaceId,
                  title: startTitle.trim() || 'Remote task',
                  objective: startObjective.trim(),
                });
              }}
            >
              <label className="text-xs text-cream/55" htmlFor="start-workspace">Start a task in a local workspace</label>
              <select
                id="start-workspace"
                value={startWorkspaceId}
                onChange={(event) => setStartWorkspaceId(event.target.value)}
                required
                className="rounded-[12px] border border-cream/15 bg-[#0c1c2e] px-3 py-2.5 text-sm text-cream focus:border-coral/60 focus:outline-none"
              >
                <option value="">Choose workspace</option>
                {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
              </select>
              <input
                value={startTitle}
                onChange={(event) => setStartTitle(event.target.value)}
                maxLength={200}
                placeholder="Task title (optional)"
                className="rounded-[12px] border border-cream/15 bg-midnight/50 px-3 py-2.5 text-sm text-cream placeholder:text-cream/35 focus:border-coral/60 focus:outline-none"
              />
              <textarea
                value={startObjective}
                onChange={(event) => setStartObjective(event.target.value)}
                maxLength={20000}
                required
                rows={3}
                placeholder="Describe what the local runtime should build…"
                className="resize-y rounded-[12px] border border-cream/15 bg-midnight/50 px-3 py-2.5 text-sm text-cream placeholder:text-cream/35 focus:border-coral/60 focus:outline-none"
              />
              <Button type="submit" disabled={!online || sending !== null || !startWorkspaceId || !startObjective.trim()}>
                {sending === 'START_TASK' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Start task
              </Button>
            </form>
            {!online && <p className="mt-3 text-xs text-gold/80">The device must be online to receive commands.</p>}
            {commandError && <p role="alert" className="mt-3 text-sm text-coral">{commandError}</p>}
          </section>
        </div>

        <div className="space-y-5">
          <section className="surface rounded-[18px] p-5">
            <div className="mb-3 flex items-center gap-2">
              <Download className="h-4 w-4 text-sky" />
              <h2 className="font-semibold text-cream">Task artifacts</h2>
            </div>
            <p className="mb-4 text-xs text-cream/50">Artifacts are task-linked, private, and expire after the configured retention period.</p>
            <label className="mb-3 block space-y-1.5 text-xs text-cream/55" htmlFor="artifact-task">
              Task
              <select
                id="artifact-task"
                value={selectedArtifactTaskId}
                onChange={(event) => setSelectedArtifactTaskId(event.target.value)}
                disabled={artifactTaskOptions.length === 0}
                className="w-full rounded-[12px] border border-cream/15 bg-[#0c1c2e] px-3 py-2.5 text-sm text-cream focus:border-coral/60 focus:outline-none"
              >
                {artifactTaskOptions.length === 0
                  ? <option value="">No task history</option>
                  : artifactTaskOptions.map((taskId) => (
                    <option key={taskId} value={taskId}>{taskId}</option>
                  ))}
              </select>
            </label>
            <form
              className="mb-4 flex flex-col gap-2 sm:flex-row"
              onSubmit={(event) => {
                event.preventDefault();
                const taskId = selectedArtifactTaskId || undefined;
                if (taskId && artifactPath.trim()) {
                  void runCommand('REQUEST_ARTIFACT_UPLOAD', { relative_path: artifactPath.trim() }, taskId);
                }
              }}
            >
              <input
                value={artifactPath}
                onChange={(event) => setArtifactPath(event.target.value)}
                maxLength={500}
                required
                placeholder="Relative task-workspace file path"
                aria-label="Task artifact path"
                className="min-w-0 flex-1 rounded-[12px] border border-cream/15 bg-midnight/50 px-3 py-2.5 text-sm text-cream placeholder:text-cream/35 focus:border-coral/60 focus:outline-none"
              />
              <Button
                type="submit"
                variant="secondary"
                disabled={!online || sending !== null || !selectedArtifactTaskId || !artifactPath.trim()}
              >
                {sending === 'REQUEST_ARTIFACT_UPLOAD' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Request upload
              </Button>
            </form>
            {artifactMessage && (
              <p role="alert" className="mb-3 rounded-xl border border-coral/20 bg-coral/10 px-3 py-2 text-xs text-coral">
                Could not load artifacts: {artifactMessage}
              </p>
            )}
            {artifacts.length > 0 ? (
              <div className="space-y-2">
                {artifacts.map((artifact) => (
                  <article key={artifact.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[12px] border border-cream/10 bg-midnight/35 p-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-cream">{artifact.name}</p>
                      <p className="mt-0.5 text-[10px] text-cream/40">
                        {(artifact.size_bytes / 1024).toFixed(1)} KiB · expires {formatTime(artifact.expires_at)}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button type="button" variant="secondary" onClick={() => void downloadArtifact(artifact)}>
                        <Download className="h-3.5 w-3.5" /> Download
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={!online || sending !== null}
                        onClick={() => void runCommand('DOWNLOAD_ARTIFACT_TO_PC', { artifact_id: artifact.id }, artifact.task_id)}
                      >
                        Send to PC
                      </Button>
                    </div>
                  </article>
                ))}
              </div>
            ) : !artifactMessage ? (
              <p className="rounded-xl border border-dashed border-cream/15 px-4 py-5 text-center text-xs text-cream/45">
                {selectedArtifactTaskId ? 'No unexpired artifacts for this task.' : 'Start or resume a task to manage its artifacts.'}
              </p>
            ) : null}
          </section>

          <section className="surface rounded-[18px] p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-coral" /><h2 className="font-semibold text-cream">Command history</h2></div>
              <span className="text-xs text-cream/40">{hasActiveCommand ? 'Polling active commands' : `${commands.length} total`}</span>
            </div>
            {commands.length === 0 ? (
              <p className="rounded-xl border border-dashed border-cream/15 px-4 py-7 text-center text-sm text-cream/45">No commands have been sent to this device.</p>
            ) : (
              <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                {commands.map((command) => {
                  const status = commandStatus(command);
                  return (
                    <article key={command.id} className="rounded-[13px] border border-cream/10 bg-midnight/35 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-mono text-sm text-cream">{command.command}</span>
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${statusStyle(status)}`}>{status}</span>
                        </div>
                        <span className="text-[10px] text-cream/40">{formatTime(command.updated_at ?? command.created_at)}</span>
                      </div>
                      {(command.output || command.error || command.result != null) && (
                        <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/20 p-2 text-[11px] text-cream/55">
                          {command.error || command.output || valueText(command.result)}
                        </pre>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="surface rounded-[18px] p-5">
            <div className="mb-4 flex items-center gap-2"><Activity className="h-4 w-4 text-coral" /><h2 className="font-semibold text-cream">Recent events</h2></div>
            {events.length === 0 ? (
              <p className={`rounded-xl border border-dashed px-4 py-6 text-center text-sm ${eventsMessage ? 'border-gold/20 text-gold/65' : 'border-cream/15 text-cream/45'}`}>
                {eventsMessage ?? 'No device events reported.'}
              </p>
            ) : (
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {events.map((event) => (
                  <article key={event.id} className="flex gap-3 rounded-[12px] border border-cream/10 bg-midnight/35 p-3">
                    <span className="mt-1 shrink-0 text-cream/45">{['error', 'failed', 'failure'].includes(String(event.type).toLowerCase()) ? <X className="h-3.5 w-3.5 text-coral" /> : <Check className="h-3.5 w-3.5 text-meadow" />}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-cream/80">{event.message || event.event_type || event.type || 'Device event'}</p>
                      <p className="mt-0.5 text-[10px] text-cream/40">{formatTime(event.timestamp ?? event.created_at)}</p>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-[12px] border border-cream/10 bg-midnight/30 px-3 py-2.5">
      <p className="text-[10px] font-semibold tracking-[0.12em] text-cream/40">{label}</p>
      <p className="mt-1 break-words text-sm font-medium text-cream/80">{value}</p>
    </div>
  );
}
