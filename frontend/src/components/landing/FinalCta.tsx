'use client';

import { MagneticButton } from '@/components/motion/MagneticButton';
import { Reveal } from '@/components/motion/Reveal';
import { WorldScene } from '@/components/world/WorldScene';

export function FinalCta() {
  return (
    <>
      <section id="pricing" className="relative overflow-hidden py-20">
        <div className="absolute inset-0 opacity-45">
          <WorldScene time="night" compact showCabin={false} />
        </div>
        <div className="relative z-10 mx-auto max-w-3xl px-6 text-center">
          <Reveal>
            <p className="font-hand text-xl text-gold">no seats, no dashboards to rent</p>
            <h2 className="mt-2 text-4xl font-semibold tracking-tight text-cream">Stay as long as you like.</h2>
            <p className="mt-4 text-[16px] text-cream/70">
              RLB is a place, not a plan grid. Bring your keys, pick your team, start a workspace.
            </p>
          </Reveal>
        </div>
      </section>
      <section className="relative min-h-[70vh] overflow-hidden">
        <WorldScene time="night" />
        <div className="absolute inset-0 bg-[#0c1c2e]/35" />
        <div className="relative z-10 flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
          <Reveal>
            <h2 className="text-5xl font-semibold leading-[0.95] tracking-tight text-cream sm:text-7xl">
              Same code.
              <br />
              A brighter place.
            </h2>
            <div className="mt-8">
              <MagneticButton href="/signup" variant="primary">
                Start Building →
              </MagneticButton>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
