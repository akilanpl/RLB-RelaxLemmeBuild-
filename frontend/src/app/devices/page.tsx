'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Activity,
  Clock3,
  Copy,
  Cpu,
  Loader2,
  Plus,
  RefreshCw,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { apiClient, type DevicePairCode, type RemoteDevice } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';

function isDeviceOnline(device: RemoteDevice): boolean {
  if (typeof device.online === 'boolean') return device.online;
  if (typeof device.is_online === 'boolean') return device.is_online;
  return ['online', 'connected', 'ready'].includes(String(device.status ?? '').toLowerCase());
}

function connectionLabel(device: RemoteDevice): string {
  const status = String(device.status ?? '').toUpperCase();
  if (status === 'RECONNECTING') return 'Reconnecting';
  if (status === 'REVOKED') return 'Revoked';
  if (status === 'OFFLINE') return 'Offline';
  return isDeviceOnline(device) ? 'Online' : 'Offline';
}

function displayDate(value: unknown): string {
  if (typeof value !== 'string' || !value) return 'Never connected';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function devicePlatform(device: RemoteDevice): string {
  const value = device.platform ?? device.operating_system ?? device.os;
  return typeof value === 'string' && value ? value : 'Platform unavailable';
}

function remainingTime(expiresAt: string, now: number): string {
  const seconds = Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1000));
  if (!Number.isFinite(seconds) || seconds === 0) return 'Expired';
  return `Expires in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function DevicesPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [devices, setDevices] = useState<RemoteDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);
  const [pairCode, setPairCode] = useState<DevicePairCode | null>(null);
  const [now, setNow] = useState(Date.now());
  const [copyMessage, setCopyMessage] = useState('');

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated, router]);

  const loadDevices = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      setDevices(await apiClient.listDevices());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load devices.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) void loadDevices();
  }, [isAuthenticated, loadDevices]);

  useEffect(() => {
    if (!pairCode) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pairCode]);

  async function generatePairCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPairing(true);
    setError(null);
    setCopyMessage('');
    try {
      const result = await apiClient.createDevicePairCode();
      setPairCode(result);
      setNow(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate a pair code.');
    } finally {
      setPairing(false);
    }
  }

  async function copyPairCode() {
    if (!pairCode) return;
    try {
      await navigator.clipboard.writeText(pairCode.pairing_token);
      setCopyMessage('Copied');
    } catch {
      setCopyMessage('Select and copy the code');
    }
  }

  if (authLoading || !isAuthenticated) {
    return <div className="flex min-h-[40vh] items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-gold" /></div>;
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-1 text-[11px] font-semibold tracking-[0.18em] text-coral/80">REMOTE MANAGEMENT</p>
          <h1 className="text-3xl font-semibold tracking-tight text-cream">Devices</h1>
          <p className="mt-1 text-sm text-cream/55">Pair a device, then monitor its connection and runtime from here.</p>
        </div>
        <Button type="button" variant="secondary" onClick={() => void loadDevices(true)} disabled={refreshing}>
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </header>

      <section className="surface grid gap-5 rounded-[18px] p-5 sm:grid-cols-[1fr_auto] sm:items-center">
        <div>
          <div className="flex items-center gap-2 text-cream">
            <Plus className="h-4 w-4 text-coral" />
            <h2 className="font-semibold">Pair a new device</h2>
          </div>
          <p className="mt-1 text-sm text-cream/55">Generate a one-time pairing token and enter it on the device you want to connect.</p>
          <form onSubmit={generatePairCode} className="mt-4 flex flex-col gap-2 sm:flex-row">
            <Button type="submit" disabled={pairing}>
              {pairing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Generate pairing token
            </Button>
          </form>
        </div>
        {pairCode && (
          <div className="min-w-0 rounded-[14px] border border-gold/25 bg-gold/5 p-4 sm:min-w-[235px]">
            <p className="text-[10px] font-semibold tracking-[0.16em] text-gold/75">PAIRING CODE</p>
            <div className="mt-1 flex items-center gap-2">
              <code className="break-all text-lg font-bold tracking-wide text-cream">{pairCode.pairing_token}</code>
              <button type="button" onClick={() => void copyPairCode()} aria-label="Copy pairing code" className="rounded-lg p-2 text-cream/65 hover:bg-paper/10 hover:text-cream">
                <Copy className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-gold">
              <Clock3 className="h-3.5 w-3.5" /> {remainingTime(pairCode.expires_at, now)}
            </p>
            {copyMessage && <p className="mt-1 text-[11px] text-cream/50" role="status">{copyMessage}</p>}
          </div>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[11px] font-semibold tracking-[0.18em] text-cream/45">CONNECTED DEVICES</h2>
          <span className="text-xs text-cream/45">{devices.length} {devices.length === 1 ? 'device' : 'devices'}</span>
        </div>
        {error && <p role="alert" className="mb-4 rounded-xl border border-coral/20 bg-coral/10 px-4 py-3 text-sm text-coral">{error}</p>}
        {loading ? (
          <div className="py-12 text-center"><Loader2 className="mx-auto h-6 w-6 animate-spin text-gold" /></div>
        ) : devices.length === 0 ? (
          <div className="surface rounded-[18px]">
            <EmptyState title="No devices paired yet" body="Generate a short-lived pair code above to connect your first device." />
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {devices.map((device) => {
              const online = isDeviceOnline(device);
              const ConnectionIcon = online ? Wifi : WifiOff;
              const status = connectionLabel(device);
              return (
                <Link
                  key={device.id}
                  href={`/devices/${encodeURIComponent(device.id)}`}
                  className="surface hover-lift group rounded-[16px] p-4 transition hover:border-cream/20"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-sky/10 text-sky"><Cpu className="h-5 w-5" /></span>
                      <div className="min-w-0">
                        <h3 className="truncate font-semibold text-cream group-hover:text-gold">{device.name}</h3>
                        <p className="truncate text-xs text-cream/45">{devicePlatform(device)}{typeof (device.version ?? device.app_version) === 'string' ? ` · ${String(device.version ?? device.app_version)}` : ''}</p>
                      </div>
                    </div>
                    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${online ? 'bg-meadow/15 text-meadow' : 'bg-cream/10 text-cream/55'}`}>
                      <ConnectionIcon className="h-3.5 w-3.5" /> {status}
                    </span>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-3 border-t border-cream/10 pt-3 text-xs text-cream/50">
                    <span className="inline-flex min-w-0 items-center gap-1.5 truncate"><Activity className="h-3.5 w-3.5 shrink-0" /> {status}</span>
                    <span className="shrink-0">Last seen {displayDate(device.last_seen_at ?? device.last_seen)}</span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
