import { cn } from '@/lib/cn';
import type { ReactNode } from 'react';
import { Loader2 } from 'lucide-react';

export function EmptyState({
  title,
  body,
  action,
  className,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('text-center px-6 py-12', className)}>
      <h3 className="text-xl font-semibold tracking-tight">{title}</h3>
      {body && <p className="mt-2 text-sm text-cream/70 max-w-md mx-auto">{body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function LoadingState({ label = 'Opening…' }: { label?: string }) {
  return (
    <div className="min-h-[50vh] flex flex-col items-center justify-center gap-3 text-cream/70">
      <Loader2 className="h-7 w-7 animate-spin text-gold" />
      <p className="text-sm">{label}</p>
    </div>
  );
}
