import { cn } from '@/lib/cn';

export function Avatar({
  name,
  size = 'md',
  className,
}: {
  name: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const letter = (name || 'R').charAt(0).toUpperCase();
  const dim = size === 'sm' ? 'h-8 w-8 text-sm' : size === 'lg' ? 'h-14 w-14 text-xl' : 'h-10 w-10 text-base';
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-full bg-gradient-to-br from-gold via-coral to-violet font-semibold text-paper shadow-soft',
        dim,
        className,
      )}
    >
      {letter}
    </span>
  );
}
