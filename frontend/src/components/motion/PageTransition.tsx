'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { useReducedMotion } from '@/components/motion/useReducedMotion';

export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const reduced = useReducedMotion();
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (reduced) return;
    setVisible(false);
    const id = window.setTimeout(() => setVisible(true), 40);
    return () => window.clearTimeout(id);
  }, [pathname, reduced]);

  return (
    <div
      style={{
        opacity: visible ? 1 : 0.001,
        transform: visible || reduced ? 'none' : 'translateY(10px)',
        transition: reduced ? 'none' : 'opacity 420ms cubic-bezier(0.22, 1, 0.36, 1), transform 420ms cubic-bezier(0.22, 1, 0.36, 1)',
      }}
    >
      {children}
    </div>
  );
}
