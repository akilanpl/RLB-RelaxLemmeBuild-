import { cn } from '@/lib/cn';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'soft';

const variants: Record<Variant, string> = {
  primary:
    'bg-coral text-paper hover:brightness-110 active:scale-[0.98] shadow-soft focus-visible:ring-coral/40',
  secondary:
    'bg-paper/12 text-cream border border-cream/15 hover:bg-paper/20 active:scale-[0.98] focus-visible:ring-cream/20',
  ghost: 'bg-transparent text-cream/80 hover:bg-paper/10 hover:text-cream focus-visible:ring-cream/15',
  danger: 'bg-rose-700/80 text-white hover:bg-rose-600 active:scale-[0.98]',
  soft: 'bg-paper text-ink hover:brightness-[1.03] active:scale-[0.98] shadow-soft focus-visible:ring-lavender/40',
};

export function Button({
  children,
  className,
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; children: ReactNode }) {
  return (
    <button
      {...props}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-[12px] px-4 py-2.5 text-sm font-semibold transition duration-200 ease-rlb',
        'focus-visible:outline-none focus-visible:ring-4',
        'disabled:pointer-events-none disabled:opacity-45',
        variants[variant],
        className,
      )}
    >
      {children}
    </button>
  );
}
