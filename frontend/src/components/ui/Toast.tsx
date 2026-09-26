'use client';

import { useEffect, useState } from 'react';
import { cn } from '@/lib/cn';

export function Toast({
  message,
  tone = 'ok',
}: {
  message: string | null;
  tone?: 'ok' | 'error';
}) {
  const [visible, setVisible] = useState(Boolean(message));
  useEffect(() => {
    setVisible(Boolean(message));
    if (!message) return;
    const id = window.setTimeout(() => setVisible(false), 4200);
    return () => window.clearTimeout(id);
  }, [message]);

  if (!message || !visible) return null;
  return (
    <div
      className={cn(
        'fixed bottom-6 right-6 z-[90] rounded-full px-4 py-2 text-sm shadow-float',
        tone === 'error' ? 'bg-coral text-paper' : 'bg-midnight text-cream',
      )}
    >
      {message}
    </div>
  );
}
