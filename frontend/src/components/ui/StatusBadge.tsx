import { cn } from '@/lib/cn';
import { StatusDot } from '@/components/ui/Badge';

const TONE: Record<string, { label: string; tone: 'good' | 'warn' | 'bad' | 'idle'; className: string }> = {
  ready: { label: 'Ready', tone: 'good', className: 'bg-meadow/15 text-meadow' },
  provisioning: { label: 'Provisioning', tone: 'warn', className: 'bg-gold/15 text-gold' },
  import_failed: { label: 'Import failed', tone: 'bad', className: 'bg-coral/15 text-coral' },
  archived: { label: 'Archived', tone: 'idle', className: 'bg-cream/10 text-cream/55' },
  running: { label: 'Running', tone: 'warn', className: 'bg-gold/15 text-gold' },
  unreachable: { label: 'Unreachable', tone: 'bad', className: 'bg-coral/15 text-coral' },
  configured: { label: 'Configured', tone: 'good', className: 'bg-meadow/15 text-meadow' },
  not_configured: { label: 'Not configured', tone: 'idle', className: 'bg-cream/10 text-cream/55' },
};

export function StatusBadge({
  status,
  className,
}: {
  status?: string | null;
  className?: string;
}) {
  const key = (status || 'ready').toLowerCase();
  const meta = TONE[key] || {
    label: status || 'Ready',
    tone: 'idle' as const,
    className: 'bg-cream/10 text-cream/70',
  };
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[10px] px-2 py-0.5 text-[11px] font-medium capitalize',
        meta.className,
        className,
      )}
    >
      <StatusDot tone={meta.tone} />
      {meta.label}
    </span>
  );
}
