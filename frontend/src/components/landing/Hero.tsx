'use client';

import { MagneticButton } from '@/components/motion/MagneticButton';
import { WorldScene } from '@/components/world/WorldScene';
import { AgentFigure } from '@/components/world/AgentFigure';
import { AGENT_ROLES } from '@/lib/agents';
import { useAuth } from '@/context/AuthContext';

export function Hero() {
  const { isAuthenticated } = useAuth();

  return (
    <section className="relative min-h-[88dvh] overflow-hidden">
      <WorldScene time="day" />
      <div className="absolute inset-0 bg-gradient-to-r from-[#f6efe4]/55 via-[#f6efe4]/20 to-transparent" />
      <div className="relative z-10 mx-auto flex min-h-[88dvh] max-w-6xl flex-col justify-end px-6 pb-16 pt-28 md:justify-center md:px-10 lg:px-12">
        <p className="font-hand text-xl text-ink/80 md:text-2xl">Good developers. Happier humans.</p>
        <h1 className="mt-2 max-w-3xl text-5xl font-semibold leading-[0.95] tracking-tight text-ink text-balance sm:text-7xl">
          A happier place to build.
        </h1>
        <p className="mt-5 max-w-lg text-[16px] leading-relaxed text-ink/75">
          RLB is your AI coding workspace where ideas, code, and creativity come together.
        </p>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <MagneticButton href={isAuthenticated ? '/dashboard' : '/signup'} variant="primary">
            Start Building →
          </MagneticButton>
          <MagneticButton href="#product" variant="paper">
            Watch how it works
          </MagneticButton>
        </div>
        <div className="mt-10 flex flex-wrap items-center gap-4">
          {AGENT_ROLES.map((role) => (
            <div key={role.id} className="flex items-center gap-2 rounded-[14px] bg-paper/80 px-3 py-2 shadow-soft backdrop-blur">
              <AgentFigure roleId={role.id} size={28} className="!animate-none" />
              <span className="text-xs font-semibold text-ink">{role.name}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
