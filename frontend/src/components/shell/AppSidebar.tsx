'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  FolderGit2,
  LayoutDashboard,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Terminal,
  Cpu,
  Users,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { Avatar } from '@/components/ui/Avatar';
import { cn } from '@/lib/cn';

const ITEMS = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, match: 'exact' as const },
  { href: '/dashboard/workspaces', label: 'Workspaces', icon: FolderGit2, match: 'prefix' as const },
  { href: '/devices', label: 'Devices', icon: Cpu, match: 'prefix' as const },
  { href: '/device-setup', label: 'Pair this desktop', icon: Cpu, match: 'exact' as const },
  { href: '/terminal', label: 'Sandbox', icon: Terminal, match: 'exact' as const },
  { href: '/loadouts', label: 'Loadouts', icon: Users, match: 'exact' as const },
  { href: '/settings', label: 'Settings', icon: Settings, match: 'exact' as const },
];

export function AppSidebar({
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, profile, isAuthenticated, logout } = useAuth();
  const [desktopMode, setDesktopMode] = useState(false);
  const displayName = profile?.display_name || user?.user_metadata?.display_name || user?.email?.split('@')[0] || 'You';
  useEffect(() => setDesktopMode(Boolean(window.rlbDesktop)), []);
  const items = ITEMS.filter((item) => item.href !== '/device-setup' || desktopMode);

  const nav = (
    <aside
      className={cn(
        'flex h-full flex-col border-r border-cream/10 bg-[#0e1a28]/95 backdrop-blur-xl',
        collapsed ? 'w-[72px]' : 'w-[232px]',
      )}
    >
      <div className={cn('flex h-14 items-center border-b border-cream/10', collapsed ? 'justify-center px-2' : 'px-4')}>
        <Link href={isAuthenticated ? '/dashboard' : '/'} className="flex items-center gap-2.5" onClick={onCloseMobile}>
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-[10px] bg-coral text-sm font-bold text-paper shadow-soft">
            R
          </span>
          {!collapsed && <span className="text-sm font-semibold tracking-tight text-cream">RLB</span>}
        </Link>
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {items.map((item) => {
          const active = item.match === 'prefix'
            ? pathname === item.href || pathname.startsWith(`${item.href}/`)
            : pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onCloseMobile}
              title={item.label}
              className={cn(
                'flex items-center gap-3 rounded-[12px] px-3 py-2.5 text-sm transition duration-200 ease-rlb',
                collapsed && 'justify-center px-0',
                active
                  ? 'bg-coral/18 text-cream shadow-[inset_0_0_0_1px_rgba(224,122,95,0.35)]'
                  : 'text-cream/60 hover:bg-paper/10 hover:text-cream',
              )}
            >
              <Icon className={cn('h-4 w-4 shrink-0', active && 'text-coral')} />
              {!collapsed && <span className="font-medium">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-cream/10 p-2">
        {isAuthenticated && (
          <Link
            href="/settings"
            onClick={onCloseMobile}
            className={cn(
              'mb-1 flex items-center gap-3 rounded-[12px] px-2 py-2 text-sm text-cream/75 hover:bg-paper/10',
              collapsed && 'justify-center px-0',
            )}
          >
            <Avatar name={displayName} size="sm" />
            {!collapsed && (
              <span className="min-w-0">
                <span className="block truncate font-medium text-cream">{displayName}</span>
                <span className="block truncate text-[11px] text-cream/45">{user?.email}</span>
              </span>
            )}
          </Link>
        )}
        <div className={cn('flex items-center', collapsed ? 'flex-col gap-1' : 'justify-between')}>
          <button
            type="button"
            onClick={onToggleCollapse}
            className="hidden rounded-[10px] p-2 text-cream/45 hover:bg-paper/10 hover:text-cream md:inline-flex"
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
          {isAuthenticated && (
            <button
              type="button"
              onClick={async () => {
                await logout();
                onCloseMobile();
                router.push('/login');
              }}
              className="inline-flex rounded-[10px] p-2 text-cream/45 hover:bg-paper/10 hover:text-coral"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );

  return (
    <>
      <div className="sticky top-0 hidden h-[100dvh] shrink-0 md:block">{nav}</div>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button type="button" className="absolute inset-0 bg-midnight/60" aria-label="Close menu" onClick={onCloseMobile} />
          <div className="absolute inset-y-0 left-0 shadow-float">{nav}</div>
        </div>
      )}
    </>
  );
}
