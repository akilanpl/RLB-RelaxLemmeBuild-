import { cn } from '@/lib/cn';
import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';

const field =
  'w-full rounded-[12px] border border-midnight/10 bg-paper px-3.5 py-2.5 text-[15px] text-ink placeholder:text-ink/35 outline-none transition duration-200 ease-rlb focus:border-coral/50 focus:ring-4 focus:ring-coral/15 disabled:opacity-50 disabled:cursor-not-allowed aria-[invalid=true]:border-coral aria-[invalid=true]:ring-4 aria-[invalid=true]:ring-coral/15';

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(field, className)} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(field, 'min-h-[88px] resize-y', className)} />;
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(field, className)} />;
}
