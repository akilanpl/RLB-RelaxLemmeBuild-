'use client';

import { useRef, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { useReducedMotion } from '@/components/motion/useReducedMotion';

export function TiltCard({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  return (
    <div
      ref={ref}
      className={cn('transition-transform duration-300 ease-rlb will-change-transform', className)}
      onMouseMove={(event) => {
        if (reduced || !ref.current) return;
        const rect = ref.current.getBoundingClientRect();
        const px = (event.clientX - rect.left) / rect.width;
        const py = (event.clientY - rect.top) / rect.height;
        const rx = (0.5 - py) * 8;
        const ry = (px - 0.5) * 10;
        ref.current.style.transform = `perspective(900px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-4px)`;
      }}
      onMouseLeave={() => {
        if (ref.current) ref.current.style.transform = 'none';
      }}
    >
      {children}
    </div>
  );
}
