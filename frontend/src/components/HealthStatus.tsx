'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { apiClient, FullHealth } from '@/lib/api';
import { RefreshCw, CheckCircle2, AlertCircle, Server, Database } from 'lucide-react';

export function HealthStatus() {
  const [health, setHealth] = useState<FullHealth | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getFullHealth();
      setHealth(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to reach API gateway';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div className="flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-indigo-950/60 border border-indigo-800/40 text-indigo-400">
            <Server className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-100">System Connectivity</h3>
            <p className="text-xs text-slate-400">FastAPI backend & Supabase PostgreSQL diagnostics</p>
          </div>
        </div>
        <button
          onClick={fetchHealth}
          disabled={loading}
          className="inline-flex items-center space-x-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>{loading ? 'Checking...' : 'Refresh'}</span>
        </button>
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Backend API Status */}
        <div className="p-4 rounded-lg bg-slate-950/50 border border-slate-800/80 flex items-start space-x-3">
          <div className="mt-0.5">
            {error ? (
              <AlertCircle className="w-5 h-5 text-rose-400" />
            ) : (
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-slate-200">FastAPI Gateway</h4>
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  error
                    ? 'bg-rose-950/60 text-rose-400 border border-rose-800/40'
                    : 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
                }`}
              >
                {error ? 'Unreachable' : health?.status === 'ok' ? 'Operational' : 'Degraded'}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400 truncate">
              {error ? error : `Environment: ${health?.environment || 'development'}`}
            </p>
          </div>
        </div>

        {/* Supabase Status */}
        <div className="p-4 rounded-lg bg-slate-950/50 border border-slate-800/80 flex items-start space-x-3">
          <div className="mt-0.5">
            <Database
              className={`w-5 h-5 ${
                health?.database?.connected
                  ? 'text-emerald-400'
                  : health?.database?.configured
                  ? 'text-amber-400'
                  : 'text-slate-500'
              }`}
            />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-slate-200">Supabase Database</h4>
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  health?.database?.connected
                    ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
                    : health?.database?.configured
                    ? 'bg-amber-950/60 text-amber-400 border border-amber-800/40'
                    : 'bg-slate-800 text-slate-400 border border-slate-700'
                }`}
              >
                {health?.database?.connected
                  ? `Connected (${health.database.latency_ms}ms)`
                  : health?.database?.configured
                  ? 'Connecting...'
                  : 'Idle (Unconfigured)'}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400 truncate">
              {health?.database?.message || 'Awaiting diagnostic probe...'}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
