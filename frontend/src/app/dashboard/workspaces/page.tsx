'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Loader2, Plus } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { fetchUserWorkspaces } from '@/lib/auth';
import { apiClient } from '@/lib/api';
import type { Workspace } from '@/types/workspace';
import { ProjectCard } from '@/components/dashboard/ProjectCard';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';
import { WorldScene } from '@/components/world/WorldScene';

export default function WorkspacesPage() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
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
      const [localRuntimeWorkspaces, cloudWorkspaces] = await Promise.all([
        apiClient.listWorkspaces(user.id).catch(() => []),
        fetchUserWorkspaces(user.id).catch(() => []),
      ]);
      const merged = new Map(localRuntimeWorkspaces.map((workspace) => [workspace.id, workspace]));
      for (const workspace of cloudWorkspaces) merged.set(workspace.id, workspace);
      setWorkspaces([...merged.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
    } catch (err: unknown) {
      setWorkspaceError(err instanceof Error ? err.message : 'Failed to fetch workspaces');
    } finally {
      setIsLoadingWorkspaces(false);
    }
  }, [user]);

  useEffect(() => {
    if (isAuthenticated && user) void loadWorkspaces();
  }, [isAuthenticated, user, loadWorkspaces]);

  if (authLoading || !isAuthenticated) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gold" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-cream">Your spaces</h1>
          <p className="mt-1 text-sm text-cream/55">Every project lives in its own isolated workspace.</p>
        </div>
        <Button type="button" onClick={() => router.push('/dashboard/workspaces/new')}>
          <Plus className="h-4 w-4" /> New workspace
        </Button>
      </div>

      {isLoadingWorkspaces ? (
        <div className="py-12 text-center"><Loader2 className="mx-auto h-6 w-6 animate-spin text-gold" /></div>
      ) : workspaceError ? (
        <p className="text-sm text-coral">{workspaceError}</p>
      ) : workspaces.length === 0 ? (
        <div className="relative overflow-hidden rounded-[20px] border border-cream/10">
          <WorldScene time="sunset" compact />
          <div className="relative">
            <EmptyState
              title="No projects yet"
              body="Create a workspace, then import your project in the IDE."
              action={
                <Link href="/dashboard/workspaces/new" className="inline-flex rounded-[12px] bg-coral px-5 py-2.5 text-sm font-semibold text-paper">
                  Create workspace
                </Link>
              }
            />
          </div>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {workspaces.map((ws, index) => (
            <ProjectCard key={ws.id} workspace={ws} index={index} />
          ))}
        </div>
      )}
    </div>
  );
}
