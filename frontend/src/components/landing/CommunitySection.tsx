'use client';

import { Reveal } from '@/components/motion/Reveal';
import { AgentFigure } from '@/components/world/AgentFigure';
import { AGENT_ROLES } from '@/lib/agents';
import { WorldScene } from '@/components/world/WorldScene';

export function CommunitySection() {
  return (
    <section id="community" className="relative overflow-hidden py-24">
      <div className="absolute inset-0 opacity-50">
        <WorldScene time="sunset" compact />
      </div>
      <div className="relative z-10 mx-auto max-w-6xl bg-gradient-to-b from-transparent via-[#0c1c2e]/40 to-[#0c1c2e]/70 px-6 py-8">
        <Reveal>
          <p className="font-hand text-xl text-paper">together</p>
          <h2 className="mt-2 text-4xl font-semibold tracking-tight text-paper sm:text-5xl">Build together.</h2>
          <p className="mt-4 max-w-xl text-[16px] text-paper/80">
            A shared hillside of builders — planners, coders, testers, and the humans who keep them honest.
          </p>
        </Reveal>
        <div className="mt-12 flex flex-wrap items-end gap-8">
          {AGENT_ROLES.map((role, index) => (
            <Reveal key={role.id} delay={index * 80}>
              <div className="text-center">
                <AgentFigure roleId={role.id} size={index === 2 ? 96 : 76} />
                <p className="mt-2 text-sm font-medium text-paper">{role.name}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
