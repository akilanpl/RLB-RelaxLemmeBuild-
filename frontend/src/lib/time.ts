export function greetingForHour(hour = new Date().getHours()): string {
  if (hour < 5) return 'Good night';
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  if (hour < 21) return 'Good evening';
  return 'Good night';
}

export function relativeTime(iso?: string): string {
  if (!iso) return 'just now';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'just now';
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function inferStack(name: string, description?: string): string {
  const hay = `${name} ${description || ''}`.toLowerCase();
  if (hay.includes('python') || hay.includes('django') || hay.includes('fastapi')) return 'Python';
  if (hay.includes('next') || hay.includes('react') || hay.includes('tsx')) return 'Next.js';
  if (hay.includes('node') || hay.includes('express')) return 'Node';
  if (hay.includes('rust')) return 'Rust';
  if (hay.includes('go') || hay.includes('golang')) return 'Go';
  if (hay.includes('swift')) return 'Swift';
  return 'TypeScript';
}

export function sceneForIndex(index: number): 'day' | 'sunset' | 'night' {
  const scenes: Array<'day' | 'sunset' | 'night'> = ['day', 'sunset', 'night'];
  return scenes[index % scenes.length];
}
