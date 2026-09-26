'use client';

import { useState } from 'react';
import Link from 'next/link';
import { MoreHorizontal } from 'lucide-react';
import { WorldScene, type WorldTime } from '@/components/world/WorldScene';
import { AgentFigure } from '@/components/world/AgentFigure';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { inferStack, relativeTime, sceneForIndex } from '@/lib/time';
import { AGENT_ROLES } from '@/lib/agents';
import type { Workspace } from '@/types/workspace';

export function ProjectCard({ workspace, index }: { workspace: Workspace; index: number }) {
  const time: WorldTime = sceneForIndex(index);
  const [menu, setMenu] = useState(false);
  const stack = inferStack(workspace.name, workspace.description);

  return (
    <article className="surface hover-lift group relative overflow-hidden rounded-[16px]">
      <Link href={`/dashboard/workspaces/${workspace.id}`} className="block">
        <div className="relative h-24 overflow-hidden">
          <WorldScene time={time} compact showCabin={index % 2 === 0} />
          <div className="absolute inset-0 bg-gradient-to-t from-[#0e1a28] via-transparent to-transparent" />
        </div>
        <div className="space-y-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <h3 className="truncate text-[15px] font-semibold text-cream">{workspace.name}</h3>
            <StatusBadge status={workspace.status || 'ready'} />
          </div>
          <p className="text-xs text-cream/55">
            {stack} · {workspace.environmentMode || 'sandboxed'}
          </p>
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-cream/40">
              {workspace.fileCount ?? 0} files · {relativeTime(workspace.updatedAt || workspace.createdAt)}
            </p>
            <div className="flex -space-x-2">
              {AGENT_ROLES.slice(0, 3).map((role) => (
                <span key={role.id} className="rounded-full bg-[#0e1a28] ring-2 ring-[#0e1a28]">
                  <AgentFigure roleId={role.id} size={22} className="!animate-none" />
                </span>
              ))}
            </div>
          </div>
        </div>
      </Link>
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setMenu((open) => !open);
        }}
        className="absolute right-3 top-[92px] rounded-[10px] p-1.5 text-cream/40 hover:bg-paper/10 hover:text-cream"
        aria-label="Workspace actions"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {menu && (
        <div className="absolute right-3 top-[124px] z-10 w-40 overflow-hidden rounded-[12px] border border-cream/10 bg-[#142433] py-1 text-xs shadow-float">
          <Link href={`/dashboard/workspaces/${workspace.id}`} className="block px-3 py-2 text-cream/80 hover:bg-paper/10">
            Open IDE
          </Link>
          <Link href="/terminal" className="block px-3 py-2 text-cream/80 hover:bg-paper/10">
            Sandbox
          </Link>
        </div>
      )}
    </article>
  );
}
