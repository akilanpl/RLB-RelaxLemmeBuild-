'use client';

import { Reveal } from '@/components/motion/Reveal';
import { AgentFigure } from '@/components/world/AgentFigure';

const SAMPLE = `export default function Home() {
  return (
    <main className="garden">
      <h1>A happier place to build.</h1>
    </main>
  );
}`;

export function IdePreview() {
  return (
    <section className="relative bg-[#0b1520] py-24">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <p className="font-hand text-xl text-gold">stay in flow</p>
          <h2 className="mt-2 max-w-2xl text-4xl font-semibold tracking-tight text-cream sm:text-5xl">
            Build without leaving your flow.
          </h2>
        </Reveal>
        <Reveal delay={120}>
          <div className="mt-10 overflow-hidden rounded-[22px] border border-cream/10 bg-[#101820] shadow-float">
            <div className="flex items-center gap-3 border-b border-cream/10 px-4 py-3 text-xs text-cream/70">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-[8px] bg-coral text-[10px] font-bold text-paper">R</span>
              <span className="font-semibold text-cream">meadow-checkout</span>
              <span className="inline-flex items-center gap-1 text-meadow">● Ready</span>
              <span className="ml-auto rounded-[8px] bg-coral px-2.5 py-1 text-[10px] font-semibold text-paper">Run</span>
            </div>
            <div className="grid min-h-[520px] md:grid-cols-[210px_1fr_260px]">
              <div className="hidden border-r border-cream/10 p-3 text-[12px] text-cream/60 md:block">
                <p className="mb-3 text-[10px] tracking-widest text-cream/40">EXPLORER</p>
                <p className="text-skyblue">app</p>
                <p className="pl-3 text-cream">page.tsx</p>
                <p className="pl-3">layout.tsx</p>
                <p className="mt-2">package.json</p>
                <p className="mt-6 text-[10px] tracking-widest text-cream/40">GIT</p>
                <p className="mt-1">main · canonical</p>
              </div>
              <div className="border-r border-cream/10">
                <div className="flex gap-1 border-b border-cream/10 px-3 py-2 text-[11px] text-cream/50">
                  <span className="rounded-[8px] bg-cream/10 px-2 py-1 text-cream">page.tsx</span>
                  <span className="px-2 py-1">layout.tsx</span>
                  <span className="ml-auto font-mono text-[10px] text-cream/35">typescript</span>
                </div>
                <pre className="overflow-auto p-5 font-mono text-[13px] leading-7 text-skyblue">{SAMPLE}</pre>
              </div>
              <div className="hidden p-4 text-xs text-cream/70 lg:block">
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-cream">RLB AI</p>
                  <span className="text-[10px] text-cream/35">default model</span>
                </div>
                <p className="mt-4 text-cream">Hey Akilan — what are we building today?</p>
                <div className="mt-4 space-y-2">
                  {['Build a new feature', 'Fix a bug', 'Write tests'].map((item) => (
                    <p key={item} className="rounded-[10px] bg-cream/5 px-3 py-2">{item}</p>
                  ))}
                </div>
                <div className="mt-6 space-y-2">
                  {['planner', 'coder', 'reviewer'].map((id) => (
                    <div key={id} className="flex items-center gap-2">
                      <AgentFigure roleId={id} size={22} className="!animate-none" />
                      <span className="capitalize text-[11px] text-cream/70">{id.replace('_', ' ')} · Ready</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
