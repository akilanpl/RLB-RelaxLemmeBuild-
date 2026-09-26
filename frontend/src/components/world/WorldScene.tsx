'use client';

import { useEffect, useRef } from 'react';
import { cn } from '@/lib/cn';
import { useReducedMotion } from '@/components/motion/useReducedMotion';

export type WorldTime = 'day' | 'sunset' | 'night';

const skies: Record<WorldTime, string> = {
  day: 'linear-gradient(180deg, #9fd6f5 0%, #c9e7f7 38%, #f3ead7 72%, #d7e8c8 100%)',
  sunset: 'linear-gradient(180deg, #f5b27a 0%, #f3c9a0 28%, #c98bb8 58%, #4a3d6b 100%)',
  night: 'linear-gradient(180deg, #0b1730 0%, #16284a 42%, #24355a 70%, #1a2c24 100%)',
};

export function WorldScene({
  time = 'day',
  className,
  compact,
  showCabin = true,
}: {
  time?: WorldTime;
  className?: string;
  compact?: boolean;
  showCabin?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const el = root.current;
    if (!el || reduced) return;
    const onMove = (event: MouseEvent) => {
      const rect = el.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      el.style.setProperty('--px', `${x}`);
      el.style.setProperty('--py', `${y}`);
    };
    window.addEventListener('mousemove', onMove);
    return () => window.removeEventListener('mousemove', onMove);
  }, [reduced]);

  return (
    <div
      ref={root}
      className={cn('absolute inset-0 overflow-hidden', className)}
      style={{ background: skies[time], ['--px' as string]: 0, ['--py' as string]: 0 }}
    >
      {time === 'day' && (
        <div
          className="absolute right-[12%] top-[10%] h-28 w-28 rounded-full bg-[#ffe7a0] blur-[1px] animate-sunpulse"
          style={{ boxShadow: '0 0 80px 24px rgba(255, 220, 140, 0.55)' }}
        />
      )}
      {time === 'sunset' && (
        <div
          className="absolute left-[18%] top-[22%] h-24 w-24 rounded-full bg-[#ffb070]"
          style={{ boxShadow: '0 0 90px 30px rgba(255, 140, 90, 0.45)' }}
        />
      )}
      {time === 'night' && (
        <>
          <div className="absolute right-[16%] top-[12%] h-16 w-16 rounded-full bg-[#f4f0d8]" style={{ boxShadow: '0 0 40px 10px rgba(244, 240, 216, 0.4)' }} />
          {Array.from({ length: 28 }).map((_, i) => (
            <span
              key={i}
              className="absolute h-1 w-1 rounded-full bg-paper animate-twinkle"
              style={{
                left: `${(i * 37) % 100}%`,
                top: `${(i * 17) % 48}%`,
                animationDelay: `${i * 0.12}s`,
                opacity: 0.7,
              }}
            />
          ))}
        </>
      )}

      <Cloud x={8} y={14} scale={1.1} delay="0s" />
      <Cloud x={58} y={10} scale={0.8} delay="1.4s" />
      <Cloud x={72} y={22} scale={1.3} delay="2.2s" />
      <Cloud x={22} y={26} scale={0.7} delay="0.6s" />

      <div
        className="absolute inset-x-0 bottom-[18%] h-[34%]"
        style={{
          transform: `translate3d(calc(var(--px) * -18px), calc(var(--py) * -8px), 0)`,
          background: time === 'night'
            ? 'linear-gradient(180deg, #2d4a3a 0%, #1d3328 100%)'
            : 'linear-gradient(180deg, #7da36a 0%, #4f7a4a 100%)',
          clipPath: 'polygon(0 42%, 12% 28%, 24% 40%, 38% 18%, 52% 34%, 68% 12%, 82% 30%, 100% 16%, 100% 100%, 0 100%)',
        }}
      />

      <div
        className="absolute inset-x-0 bottom-0 h-[28%]"
        style={{
          background: time === 'night'
            ? 'linear-gradient(180deg, #1d3a52 0%, #102433 100%)'
            : time === 'sunset'
              ? 'linear-gradient(180deg, #6a8fb8 0%, #35506e 100%)'
              : 'linear-gradient(180deg, #7eb7d6 0%, #4d8fb3 100%)',
        }}
      />

      {!compact && (
        <>
          <Island left="8%" bottom="26%" delay="0s" small />
          <Island left="74%" bottom="30%" delay="1.6s" small />
        </>
      )}
      {showCabin && <Cabin left={compact ? '28%' : '38%'} bottom="22%" />}
    </div>
  );
}

function Cloud({ x, y, scale, delay }: { x: number; y: number; scale: number; delay: string }) {
  return (
    <div
      className="absolute animate-drift"
      style={{
        left: `${x}%`,
        top: `${y}%`,
        transform: `scale(${scale}) translate3d(calc(var(--px) * 24px), calc(var(--py) * 10px), 0)`,
        animationDelay: delay,
        opacity: 0.85,
      }}
    >
      <div className="h-8 w-24 rounded-full bg-white/70 blur-[0.5px]" />
      <div className="absolute -top-3 left-6 h-10 w-16 rounded-full bg-white/80" />
      <div className="absolute -top-2 left-14 h-8 w-14 rounded-full bg-white/65" />
    </div>
  );
}

function Island({ left, bottom, delay, small }: { left: string; bottom: string; delay: string; small?: boolean }) {
  return (
    <div className="absolute animate-float" style={{ left, bottom, animationDelay: delay }}>
      <div className={small ? 'h-10 w-28' : 'h-16 w-44'} style={{ background: '#6f8f4e', borderRadius: '50% 50% 40% 40%' }} />
      <div className="mx-auto -mt-3 h-3 w-16 rounded-full bg-[#4d6a38]" />
      <div className="absolute -top-6 left-8 h-10 w-3 rounded-full bg-[#3d5a32]" />
      <div className="absolute -top-10 left-6 h-8 w-10 rounded-full bg-[#5f8a45]" />
    </div>
  );
}

function Cabin({ left, bottom }: { left: string; bottom: string }) {
  return (
    <div className="absolute animate-bob" style={{ left, bottom }}>
      <div className="relative h-28 w-40">
        <div className="absolute bottom-6 left-4 right-4 h-16 rounded-t-md bg-[#d9b48a]" />
        <div className="absolute bottom-[70px] left-1 right-1 h-10 bg-[#c46a4a]" style={{ clipPath: 'polygon(50% 0, 100% 100%, 0 100%)' }} />
        <div className="absolute bottom-10 left-8 h-7 w-5 rounded-sm bg-[#f4e3a8]" style={{ boxShadow: '0 0 12px rgba(244, 227, 168, 0.7)' }} />
        <div className="absolute bottom-6 right-8 h-9 w-6 rounded-t-sm bg-[#6a4632]" />
        <div className="absolute bottom-16 right-3 h-8 w-2 bg-[#8a5a40]" />
        <div className="absolute -bottom-1 left-2 right-2 h-7 rounded-[40%] bg-[#5f8a45]" />
        <div className="absolute bottom-7 left-[46%] h-8 w-5">
          <div className="h-4 w-5 rounded-full bg-[#f0c7a8]" />
          <div className="mx-auto h-5 w-4 rounded-sm bg-[#3d6ea8]" />
        </div>
        <p className="font-hand absolute -right-16 top-2 rotate-6 text-sm text-ink/70">home for the work</p>
      </div>
    </div>
  );
}
