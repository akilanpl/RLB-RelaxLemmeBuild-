'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { Avatar } from '@/components/ui/Avatar';

const SECTIONS = [
  { id: 'profile', label: 'Profile' },
  { id: 'account', label: 'Account' },
  { id: 'ai', label: 'AI Configuration' },
  { id: 'sandbox', label: 'Sandbox' },
  { id: 'security', label: 'Security' },
];

export default function SettingsPage() {
  const router = useRouter();
  const { user, profile, isAuthenticated, isLoading, isConfigured } = useAuth();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace('/login');
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gold" />
      </div>
    );
  }

  const displayName = profile?.display_name || user?.user_metadata?.display_name || user?.email?.split('@')[0] || 'You';

  return (
    <div className="grid gap-6 lg:grid-cols-[200px_1fr]">
      <nav className="surface h-fit space-y-1 rounded-[16px] p-2">
        {SECTIONS.map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            className="block rounded-[10px] px-3 py-2 text-sm text-cream/70 hover:bg-paper/10 hover:text-cream"
          >
            {item.label}
          </a>
        ))}
      </nav>

      <div className="space-y-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-cream">Settings</h1>
          <p className="mt-1 text-sm text-cream/55">Account, models, and sandbox — without exposing secrets.</p>
        </div>

        <section id="profile" className="surface flex items-center gap-4 rounded-[16px] p-5">
          <Avatar name={displayName} size="lg" />
          <div>
            <h2 className="text-[11px] font-semibold tracking-[0.16em] text-cream/45">PROFILE</h2>
            <p className="mt-1 text-lg font-semibold text-cream">{displayName}</p>
            <p className="text-sm text-cream/55">{user?.email}</p>
          </div>
        </section>

        <section id="account" className="surface rounded-[16px] p-5 space-y-2">
          <h2 className="text-[11px] font-semibold tracking-[0.16em] text-cream/45">ACCOUNT</h2>
          <p className="text-sm text-cream/75">Supabase Auth: {isConfigured ? 'configured' : 'not configured'}</p>
        </section>

        <section id="ai" className="surface rounded-[16px] p-5 space-y-2">
          <h2 className="text-[11px] font-semibold tracking-[0.16em] text-cream/45">AI CONFIGURATION</h2>
          <p className="text-sm text-cream/75">Credentials stay encrypted. Keys are never shown again after save.</p>
          <Link href="/loadouts" className="inline-flex text-sm text-gold hover:underline">Open loadouts →</Link>
        </section>

        <section id="sandbox" className="surface rounded-[16px] p-5 space-y-2">
          <h2 className="text-[11px] font-semibold tracking-[0.16em] text-cream/45">SANDBOX</h2>
          <p className="text-sm text-cream/75">Daytona-backed isolation. Canonical files stay read-only until you approve.</p>
          <Link href="/terminal" className="inline-flex text-sm text-gold hover:underline">View sandbox →</Link>
        </section>

        <section id="security" className="surface rounded-[16px] p-5 space-y-2">
          <h2 className="text-[11px] font-semibold tracking-[0.16em] text-cream/45">SECURITY</h2>
          <p className="text-sm text-cream/75">Human approval gates stay in front of planner, coder, and reviewer work.</p>
        </section>
      </div>
    </div>
  );
}
