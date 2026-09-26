'use client';

import { cn } from '@/lib/cn';
import { AGENT_ROLES } from '@/lib/agents';

export { AGENT_ROLES };

export function AgentFigure({
  roleId,
  size = 72,
  className,
}: {
  roleId: string;
  size?: number;
  className?: string;
}) {
  const role = AGENT_ROLES.find((item) => item.id === roleId) ?? AGENT_ROLES[0];
  return (
    <div className={cn('relative animate-bob', className)} style={{ width: size, height: size * 1.2 }}>
      <svg viewBox="0 0 80 96" width={size} height={size * 1.2} aria-hidden>
        <ellipse cx="40" cy="90" rx="18" ry="4" fill="rgba(12,28,46,0.12)" />
        <circle cx="40" cy="28" r="16" fill={role.color} />
        <circle cx="34" cy="26" r="2.2" fill="#1a2a38" />
        <circle cx="46" cy="26" r="2.2" fill="#1a2a38" />
        <path d="M34 34c4 3 8 3 12 0" stroke="#1a2a38" strokeWidth="1.6" fill="none" strokeLinecap="round" />
        <rect x="26" y="44" width="28" height="32" rx="12" fill={role.accent} />
        <rect x="18" y="48" width="10" height="18" rx="5" fill={role.color} />
        <rect x="52" y="48" width="10" height="18" rx="5" fill={role.color} />
        <rect x="30" y="74" width="8" height="14" rx="4" fill="#1a2a38" />
        <rect x="42" y="74" width="8" height="14" rx="4" fill="#1a2a38" />
      </svg>
    </div>
  );
}
