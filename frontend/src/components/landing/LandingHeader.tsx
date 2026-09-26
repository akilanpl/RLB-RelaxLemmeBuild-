'use client';

import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { MagneticButton } from '@/components/motion/MagneticButton';
import { cn } from '@/lib/cn';

const LINKS = [
  { href: '#product', label: 'Product' },
  { href: '#features', label: 'Features' },
  { href: '#community', label: 'Community' },
  { href: '#pricing', label: 'Pricing' },
];

export function LandingHeader() {
  const { isAuthenticated } = useAuth();

  return (
    <header className="absolute inset-x-0 top-0 z-30">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Link href="/" className="text-xl font-semibold tracking-tight text-ink drop-shadow-sm">
          RLB
        </Link>
        <nav className="hidden items-center gap-1 md:flex">
          {LINKS.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className={cn('rounded-full px-3 py-1.5 text-sm text-ink/70 hover:bg-paper/40 hover:text-ink')}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          {isAuthenticated ? (
            <MagneticButton href="/dashboard" variant="paper" className="px-4 py-2 text-xs">
              Open workspace
            </MagneticButton>
          ) : (
            <>
              <Link href="/login" className="rounded-full px-4 py-2 text-sm text-ink/80 hover:bg-paper/40">
                Sign in
              </Link>
              <MagneticButton href="/signup" variant="primary" className="px-4 py-2 text-xs">
                Get started
              </MagneticButton>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
