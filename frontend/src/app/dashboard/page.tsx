'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Loader2, Plus } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { fetchUserWorkspaces } from '@/lib/auth';
import type { Workspace } from '@/types/workspace';
import { greetingForHour } from '@/lib/time';
import { AGENT_ROLES } from '@/lib/agents';
import { ProjectCard } from '@/components/dashboard/ProjectCard';
import { AICommandBar } from '@/components/dashboard/AICommandBar';
import { AgentFigure } from '@/components/world/AgentFigure';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';
import { WorldScene } from '@/components/world/WorldScene';

export default function DashboardPage() {
  const router = useRouter();
  const { user, profile, isAuthenticated, isLoading: authLoading } = useAuth();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [isLoadingWorkspaces, setIsLoadingWorkspaces] = useState(true);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated, router]);

  const loadWorkspaces = useCallback(async () => {
    if (!user) return;
    setIsLoadingWorkspaces(true);
    setWorkspaceError(null);
    try {
      setWorkspaces(await fetchUserWorkspaces(user.id));
    } catch (err: unknown) {
      setWorkspaceError(err instanceof Error ? err.message : 'Failed to fetch workspaces');
    } finally {
      setIsLoadingWorkspaces(false);
    }
  }, [user]);

  useEffect(() => {
    if (isAuthenticated && user) void loadWorkspaces();
  }, [isAuthenticated, user, loadWorkspaces]);

  if (authLoading || (!isAuthenticated && typeof window !== 'undefined')) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gold" />
      </div>
    );
  }

  const userDisplayName = profile?.display_name || user?.user_metadata?.display_name || user?.email?.split('@')[0] || 'Akilan';

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-cream sm:text-4xl">
            {greetingForHour()}, {userDisplayName}.
          </h1>
          <p className="mt-1 text-[15px] text-cream/65">What are we building today?</p>
        </div>
        <Button type="button" onClick={() => router.push('/dashboard/workspaces/new')}>
          <Plus className="h-4 w-4" /> New workspace
        </Button>
      </div>

      <AICommandBar workspaces={workspaces} />

      <section>
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[11px] font-semibold tracking-[0.18em] text-cream/40">RECENT WORKSPACES</p>
          <Link href="/dashboard/workspaces" className="text-xs text-gold hover:underline">
            View all
          </Link>
        </div>
        {isLoadingWorkspaces ? (
          <div className="py-12 text-center"><Loader2 className="mx-auto h-6 w-6 animate-spin text-gold" /></div>
        ) : workspaceError ? (
          <p className="text-sm text-coral">{workspaceError}</p>
        ) : workspaces.length === 0 ? (
          <div className="relative overflow-hidden rounded-[20px] border border-cream/10">
            <div className="absolute inset-0 opacity-50"><WorldScene time="day" compact /></div>
            <div className="relative">
              <EmptyState
                title="No workspaces yet"
                body="Make a place for the next idea — import a project, start from a template, or begin empty."
                action={
                  <Link href="/dashboard/workspaces/new" className="inline-flex rounded-[12px] bg-coral px-5 py-2.5 text-sm font-semibold text-paper">
                    Create your first workspace
                  </Link>
                }
              />
            </div>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {workspaces.slice(0, 8).map((ws, index) => (
              <ProjectCard key={ws.id} workspace={ws} index={index} />
            ))}
          </div>
        )}
      </section>

      <section className="surface rounded-[18px] p-4 sm:p-5">
        <div className="mb-4 flex items-center justify-between">
          <p className="text-[11px] font-semibold tracking-[0.18em] text-cream/40">AI TEAM STATUS</p>
          <Link href="/loadouts" className="inline-flex items-center gap-1 text-xs text-gold hover:underline">
            Manage team <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
          {AGENT_ROLES.map((role) => (
            <div key={role.id} className="flex items-center gap-3 rounded-[14px] border border-cream/10 bg-[#0b1622]/70 px-3 py-2.5">
              <AgentFigure roleId={role.id} size={36} className="!animate-none" />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-cream">{role.name}</p>
                <p className="text-[11px] text-meadow">Ready</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
