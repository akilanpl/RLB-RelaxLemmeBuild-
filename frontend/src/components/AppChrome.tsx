'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { CommandPalette } from '@/components/ui/CommandPalette';
import { PageTransition } from '@/components/motion/PageTransition';
import { SmoothScroll } from '@/components/motion/SmoothScroll';
import { LandingHeader } from '@/components/landing/LandingHeader';
import { AppSidebar } from '@/components/shell/AppSidebar';
import { AppTopBar } from '@/components/shell/AppTopBar';

export function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isWorkspaceIde =
    /^\/dashboard\/workspaces\/[^/]+$/.test(pathname) && !pathname.endsWith('/new');
  const isLanding = pathname === '/';
  const isAuth = pathname === '/login' || pathname === '/signup';
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem('rlb.sidebar.collapsed') === '1');
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const toggleCollapse = () => {
    setCollapsed((value) => {
      const next = !value;
      try {
        window.localStorage.setItem('rlb.sidebar.collapsed', next ? '1' : '0');
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  if (isWorkspaceIde) {
    return (
      <div className="flex-1 min-h-0 h-[100dvh] overflow-hidden bg-[#101820]">
        {children}
      </div>
    );
  }

  if (isLanding) {
    return (
      <>
        <SmoothScroll />
        <LandingHeader />
        <CommandPalette />
        <main className="flex-1">{children}</main>
      </>
    );
  }

  if (isAuth) {
    return (
      <>
        <CommandPalette />
        <main className="flex-1">{children}</main>
      </>
    );
  }

  return (
    <div className="flex min-h-[100dvh] flex-1">
      <AppSidebar
        collapsed={collapsed}
        onToggleCollapse={toggleCollapse}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppTopBar onOpenMobile={() => setMobileOpen(true)} />
        <CommandPalette />
        <main className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <PageTransition>{children}</PageTransition>
        </main>
      </div>
    </div>
  );
}
