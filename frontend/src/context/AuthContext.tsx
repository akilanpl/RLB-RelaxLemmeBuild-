'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import type { User as SupabaseUser, Session } from '@supabase/supabase-js';
import { getSupabaseClient, isSupabaseConfigured } from '@/lib/supabase';
import { 
  signInWithEmail, 
  signUpWithEmail, 
  signOut, 
  fetchUserProfile, 
  type UserProfile 
} from '@/lib/auth';

interface AuthContextType {
  user: SupabaseUser | null;
  profile: UserProfile | null;
  session: Session | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isConfigured: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, displayName?: string) => Promise<{ session: Session | null }>;
  logout: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SupabaseUser | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const loadProfile = useCallback(async (userId: string) => {
    try {
      const userProfile = await fetchUserProfile(userId);
      setProfile(userProfile);
    } catch {
      setProfile(null);
    }
  }, []);

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setIsLoading(false);
      return;
    }

    const client = getSupabaseClient();
    if (!client) {
      setIsLoading(false);
      return;
    }

    // 1. Initial session load
    client.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      setIsLoading(false);
    }).catch(() => {
      setIsLoading(false);
    });

    // 2. Realtime auth state subscription
    const { data: { subscription } } = client.auth.onAuthStateChange(
      (_event, newSession) => {
        setSession(newSession);
        setUser(newSession?.user ?? null);
        if (!newSession?.user) {
          setProfile(null);
        }
        setIsLoading(false);
      }
    );

    return () => {
      subscription.unsubscribe();
    };
  }, [loadProfile]);

  // Fetch outside the auth callback: Supabase delivers events while holding
  // its session lock, which authenticated database requests also need.
  useEffect(() => {
    let active = true;
    setProfile(null);
    if (user?.id) {
      void fetchUserProfile(user.id).then((value) => {
        if (active) setProfile(value);
      }).catch(() => {
        if (active) setProfile(null);
      });
    }
    return () => { active = false; };
  }, [user?.id]);

  const login = async (email: string, password: string) => {
    const newSession = await signInWithEmail(email, password);
    setSession(newSession);
    setUser(newSession.user);
  };

  const signup = async (email: string, password: string, displayName?: string) => {
    const result = await signUpWithEmail(email, password, displayName);
    if (result.session) {
      setSession(result.session);
      setUser(result.session.user);
    }
    return { session: result.session };
  };

  const logout = async () => {
    await signOut();
    setUser(null);
    setProfile(null);
    setSession(null);
  };

  const refreshProfile = async () => {
    if (user) {
      await loadProfile(user.id);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        profile,
        session,
        isAuthenticated: Boolean(user),
        isLoading,
        isConfigured: isSupabaseConfigured,
        login,
        signup,
        logout,
        refreshProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
