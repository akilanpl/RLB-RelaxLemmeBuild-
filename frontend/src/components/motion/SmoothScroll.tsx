'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { useReducedMotion } from '@/components/motion/useReducedMotion';

export function SmoothScroll() {
  const pathname = usePathname();
  const reduced = useReducedMotion();
  const enabled = pathname === '/' && !reduced;
  const lenisRef = useRef<{ destroy: () => void; raf: (time: number) => void } | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let frame = 0;
    let cancelled = false;

    void import('lenis').then(({ default: Lenis }) => {
      if (cancelled) return;
      const lenis = new Lenis({
        duration: 1.15,
        smoothWheel: true,
        lerp: 0.08,
      });
      lenisRef.current = lenis;
      const raf = (time: number) => {
        lenis.raf(time);
        frame = requestAnimationFrame(raf);
      };
      frame = requestAnimationFrame(raf);
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      lenisRef.current?.destroy();
      lenisRef.current = null;
    };
  }, [enabled]);

  return null;
}
