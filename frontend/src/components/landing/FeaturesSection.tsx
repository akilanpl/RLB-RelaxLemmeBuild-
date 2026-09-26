'use client';

import { Reveal } from '@/components/motion/Reveal';
import { WorldScene } from '@/components/world/WorldScene';

const FEATURES = [
  { title: 'AI-powered development', note: 'Five minds, one workspace' },
  { title: 'File understanding', note: 'The project, not just a prompt' },
  { title: 'Isolated sandboxes', note: 'Code runs far from your desk' },
  { title: 'Human approval', note: 'Nothing lands without you' },
  { title: 'Testing', note: 'Architect, then execute' },
  { title: 'Cloud-native workspaces', note: 'Your island, always there' },
];

export function FeaturesSection() {
  return (
    <section id="features" className="relative overflow-hidden py-24">
      <div className="absolute inset-0 opacity-35">
        <WorldScene time="day" showCabin />
      </div>
      <div className="relative z-10 mx-auto max-w-6xl px-6">
        <Reveal>
          <p className="font-hand text-xl text-ink/80">the garden</p>
          <h2 className="mt-2 max-w-2xl text-4xl font-semibold tracking-tight text-ink sm:text-5xl">
            Everything you need. None of the boring stuff.
          </h2>
        </Reveal>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((item, index) => (
            <Reveal key={item.title} delay={index * 50}>
              <div className="hover-lift rounded-[18px] bg-paper/90 p-5 shadow-soft backdrop-blur">
                <h3 className="text-lg font-semibold text-ink">{item.title}</h3>
                <p className="mt-1 text-sm text-ink/60">{item.note}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
