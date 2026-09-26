import { cn } from '@/lib/cn';
import type { ReactNode } from 'react';

export function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide', className)}>
      {children}
    </span>
  );
}

export function Pill({ children, className, active }: { children: ReactNode; className?: string; active?: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-3 py-1 text-sm',
        active ? 'bg-paper/20 text-cream' : 'text-cream/70',
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({
  tone = 'good',
  className,
}: {
  tone?: 'good' | 'warn' | 'bad' | 'idle';
  className?: string;
}) {
  const color =
    tone === 'good' ? 'bg-meadow' : tone === 'warn' ? 'bg-gold' : tone === 'bad' ? 'bg-coral' : 'bg-cream/40';
  return <span className={cn('inline-block h-2 w-2 rounded-full', color, className)} />;
}

export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn('font-hand text-lg text-coral/90', className)}>{children}</p>
  );
}
