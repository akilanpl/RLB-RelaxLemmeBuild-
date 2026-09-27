'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiClient, ApiError } from '@/lib/api';
import type { CodebaseAnalysisResult } from '@/types/workspace';
import {
  Cpu,
  Layers,
  Boxes,
  Compass,
  AlertTriangle,
  RefreshCw,
  CheckCircle2,
  Clock,
  Code2,
  FolderTree,
  ShieldAlert,
} from 'lucide-react';

interface Props {
  workspaceId: string;
  userId?: string;
  fileCount: number;
}

export default function CodebaseIntelligencePanel({
  workspaceId,
  userId,
  fileCount,
}: Props) {
  const [analysis, setAnalysis] = useState<CodebaseAnalysisResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'technologies' | 'dependencies' | 'entry_points' | 'graph'>('overview');

  const fetchAnalysis = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiClient.getWorkspaceAnalysis(workspaceId, userId);
      setAnalysis(data);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) {
        // Not yet analyzed - normal state before first run
        setAnalysis(null);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load analysis');
      }
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, userId]);

  useEffect(() => {
    fetchAnalysis();
  }, [fetchAnalysis]);

  const handleRunAnalysis = async (force: boolean = false) => {
    setIsAnalyzing(true);
    setError(null);
    try {
      const data = await apiClient.triggerAnalysis(workspaceId, force, userId);
      setAnalysis(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Analysis failed to run');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950/60 text-emerald-400 border border-emerald-800/40">
            <CheckCircle2 className="w-3 h-3" />
            <span>COMPLETED</span>
          </span>
        );
      case 'running':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-950/60 text-blue-400 border border-blue-800/40">
            <RefreshCw className="w-3 h-3 animate-spin" />
            <span>RUNNING</span>
          </span>
        );
      case 'stale':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-950/60 text-amber-400 border border-amber-800/40">
            <AlertTriangle className="w-3 h-3" />
            <span>STALE (Code Modified)</span>
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-950/60 text-rose-400 border border-rose-800/40">
            <ShieldAlert className="w-3 h-3" />
            <span>FAILED</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
            <Clock className="w-3 h-3" />
            <span>PENDING</span>
          </span>
        );
    }
  };

  if (isLoading) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex items-center justify-center space-x-3 text-slate-400 text-xs">
        <RefreshCw className="w-4 h-4 animate-spin text-indigo-500" />
        <span>Inspecting codebase intelligence...</span>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg space-y-0">
      {/* Panel Header */}
      <div className="p-4 sm:p-5 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-950/40">
        <div className="flex items-center space-x-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-950/60 border border-indigo-800/40 flex items-center justify-center text-indigo-400">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-sm font-semibold text-slate-200">Codebase Intelligence</h2>
              {analysis && getStatusBadge(analysis.status)}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Deterministic static structure, framework detection, and dependency graph
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => handleRunAnalysis(true)}
            disabled={isAnalyzing || fileCount === 0}
            className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isAnalyzing ? 'animate-spin' : ''}`} />
            <span>{isAnalyzing ? 'Analyzing...' : analysis ? 'Re-analyze' : 'Run Analysis'}</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-5 my-3 p-3 rounded-xl bg-rose-950/40 border border-rose-800/40 text-rose-300 text-xs flex items-center space-x-2">
          <ShieldAlert className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {!analysis ? (
        <div className="p-10 text-center space-y-3">
          <Code2 className="w-8 h-8 text-slate-600 mx-auto" />
          <div>
            <p className="text-sm font-semibold text-slate-300">Codebase Not Yet Analyzed</p>
            <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
              Run deterministic codebase intelligence to discover frameworks, extract static dependencies, map entry points, and build import graphs.
            </p>
          </div>
          <button
            type="button"
            onClick={() => handleRunAnalysis(false)}
            disabled={isAnalyzing || fileCount === 0}
            className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-colors shadow-sm disabled:opacity-50"
          >
            <Cpu className="w-3.5 h-3.5" />
            <span>Analyze Codebase Now</span>
          </button>
        </div>
      ) : (
        <div>
          {/* Key Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 border-b border-slate-800/80 bg-slate-950/20 text-xs">
            <div className="p-3.5 border-r border-b sm:border-b-0 border-slate-800/60">
              <span className="text-slate-500 block uppercase font-medium text-[10px] tracking-wider">Total Files</span>
              <span className="text-base font-bold text-slate-200 mt-0.5 block">{analysis.indexed_files.length}</span>
            </div>
            <div className="p-3.5 border-r border-b sm:border-b-0 border-slate-800/60">
              <span className="text-slate-500 block uppercase font-medium text-[10px] tracking-wider">Languages</span>
              <span className="text-sm font-semibold text-indigo-400 mt-0.5 block truncate">
                {analysis.primary_languages.join(', ') || 'None'}
              </span>
            </div>
            <div className="p-3.5 border-r border-b sm:border-b-0 border-slate-800/60">
              <span className="text-slate-500 block uppercase font-medium text-[10px] tracking-wider">Frameworks</span>
              <span className="text-sm font-semibold text-emerald-400 mt-0.5 block truncate">
                {analysis.frameworks_detected.join(', ') || 'Standard'}
              </span>
            </div>
            <div className="p-3.5 border-r border-slate-800/60">
              <span className="text-slate-500 block uppercase font-medium text-[10px] tracking-wider">Dependencies</span>
              <span className="text-base font-bold text-slate-200 mt-0.5 block">{analysis.dependencies.length}</span>
            </div>
            <div className="p-3.5 border-r border-slate-800/60">
              <span className="text-slate-500 block uppercase font-medium text-[10px] tracking-wider">Entry Points</span>
              <span className="text-base font-bold text-slate-200 mt-0.5 block">{analysis.entry_points.length}</span>
            </div>
            <div className="p-3.5">
              <span className="text-slate-500 block uppercase font-medium text-[10px] tracking-wider">Duration</span>
              <span className="text-sm font-semibold text-slate-300 mt-0.5 block">{analysis.analysis_duration_ms} ms</span>
            </div>
          </div>

          {/* Warnings Banner if any */}
          {analysis.warnings.length > 0 && (
            <div className="p-3 bg-amber-950/30 border-b border-amber-800/30 text-xs text-amber-300 flex items-start space-x-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              <div className="space-y-0.5">
                {analysis.warnings.map((w, idx) => (
                  <p key={idx}>{w}</p>
                ))}
              </div>
            </div>
          )}

          {/* Navigation Tabs */}
          <div className="flex border-b border-slate-800 bg-slate-950/40 text-xs px-4 overflow-x-auto">
            <button
              type="button"
              onClick={() => setActiveTab('overview')}
              className={`py-3 px-3.5 font-medium border-b-2 transition-colors flex items-center space-x-1.5 whitespace-nowrap ${
                activeTab === 'overview'
                  ? 'border-indigo-500 text-indigo-300'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Cpu className="w-3.5 h-3.5" />
              <span>Overview</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('technologies')}
              className={`py-3 px-3.5 font-medium border-b-2 transition-colors flex items-center space-x-1.5 whitespace-nowrap ${
                activeTab === 'technologies'
                  ? 'border-indigo-500 text-indigo-300'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Technologies ({analysis.technologies.length})</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('dependencies')}
              className={`py-3 px-3.5 font-medium border-b-2 transition-colors flex items-center space-x-1.5 whitespace-nowrap ${
                activeTab === 'dependencies'
                  ? 'border-indigo-500 text-indigo-300'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Boxes className="w-3.5 h-3.5" />
              <span>Dependencies ({analysis.dependencies.length})</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('entry_points')}
              className={`py-3 px-3.5 font-medium border-b-2 transition-colors flex items-center space-x-1.5 whitespace-nowrap ${
                activeTab === 'entry_points'
                  ? 'border-indigo-500 text-indigo-300'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Compass className="w-3.5 h-3.5" />
              <span>Entry Points ({analysis.entry_points.length})</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('graph')}
              className={`py-3 px-3.5 font-medium border-b-2 transition-colors flex items-center space-x-1.5 whitespace-nowrap ${
                activeTab === 'graph'
                  ? 'border-indigo-500 text-indigo-300'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <FolderTree className="w-3.5 h-3.5" />
              <span>Dependency Graph ({analysis.dependency_graph.edges.length})</span>
            </button>
          </div>

          {/* Tab Content */}
          <div className="p-5 text-xs text-slate-300">
            {activeTab === 'overview' && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    Deterministic Architecture Summary
                  </h3>
                  <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800/80 font-mono text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">
                    {analysis.architecture_overview}
                  </div>
                </div>

                <div className="flex items-center space-x-2 text-[11px] text-slate-500 font-mono">
                  <span>Analysis Version: {analysis.analysis_version}</span>
                  <span>•</span>
                  <span>Snapshot: {analysis.source_snapshot_hash || 'Initial'}</span>
                  <span>•</span>
                  <span>Analyzed: {new Date(analysis.created_at).toLocaleString()}</span>
                </div>
              </div>
            )}

            {activeTab === 'technologies' && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {analysis.technologies.length === 0 ? (
                  <p className="text-slate-500 italic col-span-full">No framework technologies identified.</p>
                ) : (
                  analysis.technologies.map((t, idx) => (
                    <div
                      key={idx}
                      className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800/80 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-200">{t.name}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-indigo-950/70 text-indigo-300 border border-indigo-800/40">
                          {t.category}
                        </span>
                      </div>
                      <div className="text-[11px] text-emerald-400 font-medium">
                        Confidence: {(t.confidence * 100).toFixed(0)}%
                      </div>
                      <div className="space-y-1 text-[11px] text-slate-400">
                        {t.evidence.map((ev, i) => (
                          <div key={i} className="flex items-start space-x-1.5">
                            <span className="text-indigo-400 mt-0.5">•</span>
                            <span>{ev}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === 'dependencies' && (
              <div className="space-y-3">
                {analysis.dependencies.length === 0 ? (
                  <p className="text-slate-500 italic">No package manifests found.</p>
                ) : (
                  <div className="max-h-[400px] overflow-y-auto rounded-xl border border-slate-800">
                    <table className="w-full text-left border-collapse">
                      <thead className="bg-slate-950/80 text-[10px] uppercase font-semibold text-slate-400 border-b border-slate-800 sticky top-0">
                        <tr>
                          <th className="py-2.5 px-4">Package</th>
                          <th className="py-2.5 px-4">Version Spec</th>
                          <th className="py-2.5 px-4">Type</th>
                          <th className="py-2.5 px-4">Manifest</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                        {analysis.dependencies.map((d, idx) => (
                          <tr key={idx} className="hover:bg-slate-800/30">
                            <td className="py-2 px-4 text-slate-200 font-semibold">{d.name}</td>
                            <td className="py-2 px-4 text-indigo-300">{d.version_spec || '*'}</td>
                            <td className="py-2 px-4">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] ${
                                  d.dependency_type === 'production'
                                    ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/30'
                                    : 'bg-slate-800 text-slate-400 border border-slate-700'
                                }`}
                              >
                                {d.dependency_type}
                              </span>
                            </td>
                            <td className="py-2 px-4 text-slate-500">{d.manifest_source}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'entry_points' && (
              <div className="space-y-3">
                {analysis.entry_points.length === 0 ? (
                  <p className="text-slate-500 italic">No conventional entry points detected.</p>
                ) : (
                  analysis.entry_points.map((ep, idx) => (
                    <div
                      key={idx}
                      className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                    >
                      <div className="space-y-1">
                        <div className="flex items-center space-x-2">
                          <Compass className="w-4 h-4 text-indigo-400" />
                          <span className="font-mono font-semibold text-slate-200">{ep.path}</span>
                        </div>
                        <p className="text-[11px] text-slate-400 pl-6">{ep.evidence.join(', ')}</p>
                      </div>
                      <div className="flex items-center space-x-2 flex-shrink-0">
                        <span className="px-2.5 py-1 rounded-md text-[10px] font-mono bg-indigo-950/70 text-indigo-300 border border-indigo-800/40">
                          {ep.entry_type}
                        </span>
                        <span className="text-[11px] text-emerald-400 font-semibold">
                          {(ep.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === 'graph' && (
              <div className="space-y-3">
                <div className="text-[11px] text-slate-400">
                  Static import and module dependency edges ({analysis.dependency_graph.edges.length} connections across {analysis.dependency_graph.nodes.length} nodes).
                </div>
                {analysis.dependency_graph.edges.length === 0 ? (
                  <p className="text-slate-500 italic">No module import relationships mapped.</p>
                ) : (
                  <div className="max-h-[350px] overflow-y-auto space-y-1.5 font-mono text-[11px]">
                    {analysis.dependency_graph.edges.map((e, idx) => (
                      <div
                        key={idx}
                        className="p-2 rounded bg-slate-950/60 border border-slate-800/60 flex items-center justify-between"
                      >
                        <span className="text-slate-300 truncate max-w-[45%]">{e.source}</span>
                        <span className="text-indigo-400 text-xs">→</span>
                        <span className="text-emerald-300 truncate max-w-[45%]">{e.target}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
