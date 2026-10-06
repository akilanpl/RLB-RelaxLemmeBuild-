/**
 * Authentication service abstraction.
 * Encapsulates Supabase Auth calls, sanitizes error messages,
 * and interacts with the Phase 0 `users` and `workspaces` entities.
 */

import { getSupabaseClient, isSupabaseConfigured } from './supabase';
import type { User as SupabaseUser, Session } from '@supabase/supabase-js';
import type { Workspace } from '@/types/workspace';

export interface UserProfile {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuthState {
  user: SupabaseUser | null;
  profile: UserProfile | null;
  session: Session | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isConfigured: boolean;
}

export function sanitizeAuthError(error: unknown): string {
  if (!error) return 'An unexpected error occurred.';

  const message = (error as { message?: string }).message || String(error);

  if (message.includes('Invalid login credentials')) {
    return 'Invalid email or password. Please try again.';
  }
  if (message.includes('User already registered') || message.includes('already exists')) {
    return 'An account with this email already exists. Please sign in instead.';
  }
  if (message.includes('Password should be at least')) {
    return 'Password must be at least 6 characters long.';
  }
  if (message.includes('valid email') || message.includes('invalid email')) {
    return 'Please enter a valid email address.';
  }
  if (message.includes('Network') || message.includes('fetch')) {
    return 'Network communication failure. Please check your internet connection.';
  }
  if (message.includes('Email not confirmed')) {
    return 'Your email address has not been confirmed yet. Please check your inbox.';
  }
  if (message.includes('Auth session missing') || message.includes('JWT expired')) {
    return 'Your session has expired. Please sign in again.';
  }

  return 'Authentication service error. Please try again later.';
}

export async function signInWithEmail(email: string, password: string): Promise<Session> {
  if (!isSupabaseConfigured) {
    throw new Error('Supabase authentication is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.');
  }

  const client = getSupabaseClient();
  if (!client) {
    throw new Error('Supabase client failed to initialize.');
  }

  const { data, error } = await client.auth.signInWithPassword({
    email: email.trim(),
    password,
  });

  if (error) {
    throw new Error(sanitizeAuthError(error));
  }

  if (!data.session) {
    throw new Error('Sign in succeeded but no active session was returned.');
  }

  return data.session;
}

export async function signUpWithEmail(
  email: string, 
  password: string, 
  displayName?: string
): Promise<{ user: SupabaseUser | null; session: Session | null }> {
  if (!isSupabaseConfigured) {
    throw new Error('Supabase authentication is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.');
  }

  const client = getSupabaseClient();
  if (!client) {
    throw new Error('Supabase client failed to initialize.');
  }

  const { data, error } = await client.auth.signUp({
    email: email.trim(),
    password,
    options: {
      data: {
        display_name: displayName?.trim() || email.split('@')[0],
      },
    },
  });

  if (error) {
    throw new Error(sanitizeAuthError(error));
  }

  return { user: data.user, session: data.session };
}

export async function signOut(): Promise<void> {
  if (!isSupabaseConfigured) return;

  const client = getSupabaseClient();
  if (!client) return;

  const { error } = await client.auth.signOut();
  if (error) {
    throw new Error(sanitizeAuthError(error));
  }
}

export async function fetchUserProfile(userId: string): Promise<UserProfile | null> {
  if (!isSupabaseConfigured) return null;

  const client = getSupabaseClient();
  if (!client) return null;

  const { data, error } = await client
    .from('users')
    .select('*')
    .eq('id', userId)
    .single();

  if (error) {
    return null;
  }

  return data as UserProfile;
}

export async function fetchUserWorkspaces(userId?: string): Promise<Workspace[]> {
  if (typeof window !== 'undefined' && window.rlbDesktop) {
    const { apiClient } = await import('@/lib/api');
    return apiClient.listWorkspaces(userId);
  }
  if (isSupabaseConfigured) {
    const client = getSupabaseClient();
    if (client) {
      // RLS automatically filters to workspaces where user_id = auth.uid()
      const { data, error } = await client
        .from('workspaces')
        .select('*')
        .eq('is_archived', false)
        .order('created_at', { ascending: false });

      if (!error && Array.isArray(data) && data.length > 0) {
        const { normalizeWorkspaceList } = await import('@/lib/api');
        return normalizeWorkspaceList(data);
      }
    }
  }

  const { apiClient } = await import('@/lib/api');
  return apiClient.listWorkspaces(userId);
}

