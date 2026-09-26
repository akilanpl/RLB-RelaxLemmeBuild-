'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { Avatar } from '@/components/ui/Avatar';
import { cn } from '@/lib/cn';

const ITEMS = [
  { href: '/dashboard', label: 'Dashboard', match: 'exact' as const },
  { href: '/dashboard/workspaces', label: 'Workspaces', match: 'prefix' as const },
  { href: '/terminal', label: 'Sandbox', match: 'exact' as const },
  { href: '/loadouts', label: 'Loadouts', match: 'exact' as const },
  { href: '/settings', label: 'Settings', match: 'exact' as const },
];

export function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, profile, isAuthenticated, logout, isLoading } = useAuth();
  const displayName = profile?.display_name || user?.user_metadata?.display_name || user?.email?.split('@')[0] || 'You';

  return (
    <header className="sticky top-4 z-40 mx-auto w-[min(1120px,calc(100%-1.5rem))]">
      <div className="glass-dark flex items-center justify-between rounded-full px-4 py-2 shadow-float">
        <Link href={isAuthenticated ? '/dashboard' : '/'} className="px-2 text-sm font-semibold tracking-tight text-cream">
          RLB
        </Link>
        <nav className="hidden items-center gap-0.5 md:flex">
          {ITEMS.map((item) => {
            const active = item.match === 'prefix'
              ? pathname === item.href || pathname.startsWith(`${item.href}/`)
              : pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'rounded-full px-3 py-1.5 text-sm transition',
                  active ? 'bg-paper/15 text-cream' : 'text-cream/60 hover:text-cream',
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-2">
          {!isLoading && isAuthenticated && (
            <>
              <Link href="/settings" className="hidden items-center gap-2 sm:flex">
                <Avatar name={displayName} size="sm" />
              </Link>
              <button
                type="button"
                onClick={async () => {
                  await logout();
                  router.push('/login');
                }}
                className="rounded-full px-3 py-1.5 text-xs text-cream/70 hover:text-cream"
              >
                Sign out
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
