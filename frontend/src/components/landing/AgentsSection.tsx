'use client';

import { Reveal } from '@/components/motion/Reveal';
import { AGENT_ROLES } from '@/lib/agents';
import { AgentFigure } from '@/components/world/AgentFigure';

export function AgentsSection() {
  return (
    <section id="product" className="relative bg-[#0f1c24] py-24">
      <div className="relative z-10 mx-auto max-w-6xl px-6">
        <Reveal>
          <p className="font-hand text-xl text-gold">the team</p>
          <h2 className="mt-2 max-w-2xl text-4xl font-semibold tracking-tight text-cream sm:text-5xl">
            Different minds. A better build.
          </h2>
        </Reveal>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {AGENT_ROLES.map((role, index) => (
            <Reveal key={role.id} delay={index * 70}>
              <div className="hover-lift surface h-full rounded-[18px] p-5 text-cream">
                <AgentFigure roleId={role.id} size={64} />
                <h3 className="mt-3 text-lg font-semibold">{role.name}</h3>
                <p className="mt-1 text-sm leading-relaxed text-cream/70">{role.description}</p>
                <p className="font-hand mt-3 text-sm text-gold">{role.personality}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
