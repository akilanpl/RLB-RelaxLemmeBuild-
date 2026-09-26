'use client';

import { AGENT_ROLES } from '@/lib/agents';
import { cn } from '@/lib/cn';

const STATUS_TO_ROLE: Record<string, string> = {
  planning: 'planner',
  plan_review: 'planner',
  coding: 'coder',
  code_review: 'coder',
  test_planning: 'test_architect',
  test_executing: 'test_executor',
  repairing: 'coder',
  reviewing: 'reviewer',
};

export function AgentActivity({
  status,
  busyLabel,
}: {
  status?: string | null;
  busyLabel?: string | null;
}) {
  const active = STATUS_TO_ROLE[status || ''] || (busyLabel ? 'planner' : null);

  return (
    <div className="space-y-2">
      {AGENT_ROLES.map((role) => {
        const on = active === role.id;
        return (
          <div
            key={role.id}
            className={cn(
              'flex items-center gap-3 rounded-[12px] px-3 py-2 text-xs transition',
              on ? 'bg-gold/10 text-cream' : 'text-cream/50',
            )}
          >
            <span className={cn('h-2 w-2 rounded-full', on ? 'bg-gold animate-pulse-dot' : 'bg-cream/25')} />
            <span className="font-semibold tracking-wide uppercase text-[10px] w-28 shrink-0">{role.name}</span>
            <span>{on ? (busyLabel || role.idle) : 'Idle'}</span>
          </div>
        );
      })}
    </div>
  );
}
