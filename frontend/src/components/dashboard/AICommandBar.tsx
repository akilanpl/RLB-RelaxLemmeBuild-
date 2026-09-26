'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowUp, Sparkles } from 'lucide-react';
import type { Workspace } from '@/types/workspace';

const SUGGESTIONS = [
  'Build a feature',
  'Fix a bug',
  'Explain this code',
  'Write tests',
];

export const PENDING_PROMPT_KEY = 'rlb.pendingPrompt';

export function AICommandBar({ workspaces }: { workspaces: Workspace[] }) {
  const router = useRouter();
  const [value, setValue] = useState('');

  const go = (text: string) => {
    const prompt = text.trim();
    if (!prompt) return;
    try {
      window.sessionStorage.setItem(PENDING_PROMPT_KEY, prompt);
    } catch {
      /* ignore */
    }
    const latest = workspaces[0];
    if (latest) router.push(`/dashboard/workspaces/${latest.id}`);
    else router.push('/dashboard/workspaces/new');
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    go(value);
  };

  return (
    <div className="surface rounded-[18px] p-4 sm:p-5">
      <form onSubmit={onSubmit} className="flex items-end gap-3 rounded-[14px] border border-cream/10 bg-[#0b1622] p-3">
        <Sparkles className="mb-2 hidden h-4 w-4 shrink-0 text-gold sm:block" />
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          rows={2}
          placeholder="Ask RLB to build something..."
          className="min-h-[52px] w-full resize-none bg-transparent text-[15px] text-cream outline-none placeholder:text-cream/35"
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              go(value);
            }
          }}
        />
        <button
          type="submit"
          disabled={!value.trim()}
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-coral text-paper transition hover:brightness-110 disabled:opacity-40"
          aria-label="Send"
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => go(item)}
            className="rounded-[10px] border border-cream/10 bg-paper/5 px-3 py-1.5 text-xs text-cream/75 transition hover:-translate-y-0.5 hover:border-coral/30 hover:text-cream"
          >
            {item}
          </button>
        ))}
      </div>
    </div>
  );
}
