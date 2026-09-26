'use client';

import Link from 'next/link';
import { useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { useReducedMotion } from '@/components/motion/useReducedMotion';

type Variant = 'primary' | 'secondary' | 'ghost' | 'paper';

const variants: Record<Variant, string> = {
  primary: 'bg-coral text-paper shadow-float hover:brightness-105',
  secondary: 'bg-paper/15 text-cream border border-cream/25 hover:bg-paper/25',
  ghost: 'bg-transparent text-cream hover:bg-paper/10',
  paper: 'bg-paper text-ink shadow-soft hover:brightness-[1.02]',
};

interface SharedProps {
  children: ReactNode;
  className?: string;
  variant?: Variant;
  href?: string;
}

export function MagneticButton({
  children,
  className,
  variant = 'primary',
  href,
  ...props
}: SharedProps & ButtonHTMLAttributes<HTMLButtonElement>) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();

  const onMove = (event: React.MouseEvent<HTMLElement>) => {
    if (reduced || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = event.clientX - rect.left - rect.width / 2;
    const y = event.clientY - rect.top - rect.height / 2;
    ref.current.style.transform = `translate(${x * 0.18}px, ${y * 0.18}px)`;
  };

  const onLeave = () => {
    if (!ref.current) return;
    ref.current.style.transform = 'translate(0, 0)';
  };

  const classes = cn(
    'inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-semibold tracking-tight',
    variants[variant],
    className,
  );

  return (
    <span
      ref={ref}
      className="inline-flex transition-transform duration-300 ease-rlb will-change-transform"
      onMouseMove={onMove}
      onMouseLeave={onLeave}
    >
      {href ? (
        <Link href={href} className={classes}>
          {children}
        </Link>
      ) : (
        <button type="button" {...props} className={classes}>
          {children}
        </button>
      )}
    </span>
  );
}
