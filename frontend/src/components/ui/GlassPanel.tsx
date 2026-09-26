import { cn } from '@/lib/cn';
import type { ReactNode } from 'react';

export function GlassPanel({
  children,
  className,
  dark,
}: {
  children: ReactNode;
  className?: string;
  dark?: boolean;
}) {
  return <div className={cn(dark ? 'glass-dark' : 'glass', 'rounded-[16px]', className)}>{children}</div>;
}

export function FloatingPanel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('paper rounded-rlb p-6 shadow-float', className)}>
      {children}
    </div>
  );
}
