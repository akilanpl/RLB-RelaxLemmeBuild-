'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';

const ROUTES = [
  { href: '/dashboard', label: 'Dashboard', needAuth: true },
  { href: '/dashboard/workspaces', label: 'Workspaces', needAuth: true },
  { href: '/dashboard/workspaces/new', label: 'New workspace', needAuth: true },
  { href: '/loadouts', label: 'Loadouts', needAuth: true },
  { href: '/settings', label: 'Settings', needAuth: true },
  { href: '/terminal', label: 'Sandbox', needAuth: true },
  { href: '/', label: 'Home', needAuth: false },
];

export function CommandPalette() {
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen((value) => !value);
      }
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const items = useMemo(() => {
    const q = query.toLowerCase();
    return ROUTES.filter((item) => (!item.needAuth || isAuthenticated) && item.label.toLowerCase().includes(q));
  }, [query, isAuthenticated]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[18vh] px-4">
      <button type="button" className="absolute inset-0 bg-midnight/50 backdrop-blur-sm" onClick={() => setOpen(false)} aria-label="Close command palette" />
      <div role="dialog" aria-label="Command palette" className="relative w-full max-w-lg paper rounded-rlb shadow-float overflow-hidden">
        <label className="sr-only" htmlFor="command-palette-input">Go somewhere</label>
        <input
          id="command-palette-input"
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Go somewhere…"
          className="w-full border-b border-midnight/10 bg-transparent px-5 py-4 text-ink outline-none"
        />
        <div className="max-h-72 overflow-auto p-2">
          {items.map((item) => (
            <button
              key={item.href}
              type="button"
              className="w-full rounded-2xl px-4 py-3 text-left text-sm text-ink hover:bg-lavender/20"
              onClick={() => {
                setOpen(false);
                router.push(item.href);
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
