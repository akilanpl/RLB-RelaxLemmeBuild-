'use client';

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { ArrowLeft, Loader2, ShieldCheck, Wifi } from 'lucide-react';
import { Button } from '@/components/ui/Button';

export default function DeviceSetupPage() {
  const [controlPlaneUrl, setControlPlaneUrl] = useState(process.env.NEXT_PUBLIC_CONTROL_API_URL ?? '');
  const [pairingToken, setPairingToken] = useState('');
  const [name, setName] = useState('RLB Windows device');
  const [busy, setBusy] = useState(false);
  const [pairedDevice, setPairedDevice] = useState<{ id: string; name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function pair(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!window.rlbDesktop) {
      setError('Device pairing must be completed inside the RLB desktop app.');
      return;
    }
    setBusy(true);
    setError(null);
    setPairedDevice(null);
    try {
      const result = await window.rlbDesktop.pairDevice({
        controlPlaneUrl: controlPlaneUrl.trim(),
        pairingToken: pairingToken.trim(),
        name: name.trim() || 'RLB Windows device',
      });
      setPairedDevice(result);
      setPairingToken('');
      window.location.assign('/dashboard');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not pair this device.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link href="/devices" className="inline-flex items-center gap-2 text-sm text-cream/60 hover:text-cream">
        <ArrowLeft className="h-4 w-4" /> Devices
      </Link>
      <header>
        <p className="mb-1 text-[11px] font-semibold tracking-[0.18em] text-coral/80">DESKTOP SETUP</p>
        <h1 className="text-3xl font-semibold tracking-tight text-cream">Pair this device</h1>
        <p className="mt-2 text-sm text-cream/55">
          Enter the one-time pairing token created from your signed-in web account.
          The device credential is stored using the operating system&apos;s secure storage.
        </p>
      </header>

      <form onSubmit={pair} className="surface space-y-4 rounded-[18px] p-5 sm:p-6">
        <label className="block space-y-1.5 text-sm text-cream/75">
          Control plane URL
          <input
            type="url"
            value={controlPlaneUrl}
            onChange={(event) => setControlPlaneUrl(event.target.value)}
            required
            placeholder="https://api.example.com"
            className="w-full rounded-[12px] border border-cream/15 bg-midnight/50 px-3 py-2.5 text-cream placeholder:text-cream/35 focus:border-coral/60 focus:outline-none"
          />
        </label>
        <label className="block space-y-1.5 text-sm text-cream/75">
          Device name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            required
            className="w-full rounded-[12px] border border-cream/15 bg-midnight/50 px-3 py-2.5 text-cream focus:border-coral/60 focus:outline-none"
          />
        </label>
        <label className="block space-y-1.5 text-sm text-cream/75">
          One-time pairing token
          <textarea
            value={pairingToken}
            onChange={(event) => setPairingToken(event.target.value)}
            minLength={20}
            maxLength={200}
            required
            rows={3}
            autoComplete="off"
            className="w-full resize-y rounded-[12px] border border-cream/15 bg-midnight/50 px-3 py-2.5 font-mono text-sm text-cream focus:border-coral/60 focus:outline-none"
          />
        </label>
        <Button type="submit" disabled={busy || !pairingToken.trim()}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wifi className="h-4 w-4" />}
          Pair and connect
        </Button>
        {pairedDevice && (
          <p role="status" className="flex items-center gap-2 rounded-xl bg-meadow/10 px-3 py-2.5 text-sm text-meadow">
            <ShieldCheck className="h-4 w-4" />
            {pairedDevice.name} is paired. Its outbound session is starting.
          </p>
        )}
        {error && <p role="alert" className="rounded-xl bg-coral/10 px-3 py-2.5 text-sm text-coral">{error}</p>}
      </form>
      <p className="text-xs leading-5 text-cream/40">
        The pairing token expires quickly and can be used once. The long-lived device credential never enters
        browser storage and is encrypted by the desktop app before it is saved.
      </p>
    </div>
  );
}
