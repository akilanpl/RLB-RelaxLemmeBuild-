'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Menu } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { Avatar } from '@/components/ui/Avatar';
import { SystemHealthChip } from '@/components/dashboard/SystemHealthChip';

const TITLES: Array<{ test: (path: string) => boolean; title: string; subtitle?: string }> = [
  { test: (p) => p === '/dashboard', title: 'Dashboard', subtitle: 'Your creative home' },
  { test: (p) => p === '/dashboard/workspaces/new', title: 'New workspace', subtitle: 'Make a place for it' },
  { test: (p) => p.startsWith('/dashboard/workspaces'), title: 'Workspaces', subtitle: 'Projects and islands' },
  { test: (p) => p === '/loadouts', title: 'Loadouts', subtitle: 'How your team thinks' },
  { test: (p) => p === '/terminal', title: 'Sandbox', subtitle: 'Isolated runtime' },
  { test: (p) => p === '/settings', title: 'Settings', subtitle: 'Account and environment' },
];

export function AppTopBar({ onOpenMobile }: { onOpenMobile: () => void }) {
  const pathname = usePathname();
  const { user, profile } = useAuth();
  const displayName = profile?.display_name || user?.user_metadata?.display_name || user?.email?.split('@')[0] || 'You';
  const meta = TITLES.find((item) => item.test(pathname));

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-cream/10 bg-[#0e1a28]/80 px-3 backdrop-blur-xl sm:px-5">
      <button
        type="button"
        onClick={onOpenMobile}
        className="inline-flex rounded-[10px] p-2 text-cream/70 hover:bg-paper/10 md:hidden"
        aria-label="Open navigation"
      >
        <Menu className="h-4 w-4" />
      </button>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-cream">{meta?.title || 'RLB'}</p>
        {meta?.subtitle && <p className="hidden truncate text-[11px] text-cream/45 sm:block">{meta.subtitle}</p>}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <SystemHealthChip />
        <Link href="/settings" className="hidden items-center gap-2 rounded-[12px] px-1.5 py-1 hover:bg-paper/10 sm:flex">
          <Avatar name={displayName} size="sm" />
        </Link>
      </div>
    </header>
  );
}
