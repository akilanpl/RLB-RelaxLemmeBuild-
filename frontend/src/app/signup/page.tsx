'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertCircle, ArrowRight, CheckCircle2, Loader2 } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { WorldScene } from '@/components/world/WorldScene';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { AgentFigure } from '@/components/world/AgentFigure';

export default function SignupPage() {
  const router = useRouter();
  const { signup, isAuthenticated, isLoading: authLoading, isConfigured } = useAuth();
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!authLoading && isAuthenticated) router.replace('/dashboard');
  }, [authLoading, isAuthenticated, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMessage(null);
    if (!email.trim() || !password) {
      setError('Please provide all required fields.');
      return;
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters long.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setIsSubmitting(true);
    try {
      const { session } = await signup(email, password, displayName);
      if (session) router.push('/dashboard');
      else setSuccessMessage('Registration successful! If required, please verify your email before logging in.');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Registration failed.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gold" />
      </div>
    );
  }

  return (
    <div className="grid min-h-[100dvh] lg:grid-cols-[1.15fr_0.85fr]">
      <div className="relative hidden min-h-[40vh] lg:block">
        <WorldScene time="day" />
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#0c1c2e]/70 to-transparent px-10 pb-10 pt-24">
          <p className="font-hand text-2xl text-paper">let’s make a place for it</p>
          <div className="mt-4 flex gap-3">
            {['planner', 'coder', 'test_architect', 'reviewer'].map((id) => (
              <AgentFigure key={id} roleId={id} size={40} />
            ))}
          </div>
        </div>
      </div>
      <div className="relative flex items-center justify-center bg-cream px-6 py-16">
        <Link href="/" className="absolute left-6 top-6 text-sm font-semibold text-ink">RLB</Link>
        <div className="w-full max-w-[380px]">
          <h1 className="text-[2.25rem] font-semibold leading-tight tracking-tight text-ink">Let’s build something.</h1>
          <p className="mt-2 text-[15px] text-ink/60">A name, an email, and a quiet workspace of your own.</p>

          {!isConfigured && (
            <div className="mt-6 flex gap-2 rounded-[12px] bg-gold/20 p-3 text-xs text-ink">
              <AlertCircle className="h-4 w-4 shrink-0" />
              Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in frontend/.env.local.
            </div>
          )}
          {error && (
            <div className="mt-6 flex gap-2 rounded-[12px] bg-coral/15 p-3 text-sm text-coral">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}
          {successMessage && (
            <div className="mt-6 flex gap-2 rounded-[12px] bg-meadow/15 p-3 text-sm text-meadow">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <div>
                {successMessage}
                <Link href="/login" className="mt-2 block font-medium underline">Proceed to Sign In →</Link>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            <label className="block text-xs font-medium text-ink/70">
              Name
              <Input className="mt-1.5" id="displayName" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Akilan" disabled={!isConfigured || isSubmitting} />
            </label>
            <label className="block text-xs font-medium text-ink/70">
              Email
              <Input className="mt-1.5" id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@studio.com" required disabled={!isConfigured || isSubmitting} />
            </label>
            <label className="block text-xs font-medium text-ink/70">
              Password
              <Input className="mt-1.5" id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Min. 6 characters" required disabled={!isConfigured || isSubmitting} aria-invalid={password.length > 0 && password.length < 6} />
            </label>
            <label className="block text-xs font-medium text-ink/70">
              Confirm password
              <Input className="mt-1.5" id="confirmPassword" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Repeat password" required disabled={!isConfigured || isSubmitting} aria-invalid={confirmPassword.length > 0 && confirmPassword !== password} />
            </label>
            <Button type="submit" disabled={!isConfigured || isSubmitting} className="w-full">
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
              {isSubmitting ? 'Creating account…' : 'Create account'}
            </Button>
          </form>
          <p className="mt-6 text-sm text-ink/60">
            Already here? <Link href="/login" className="font-semibold text-coral">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
