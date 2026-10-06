'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { cn } from '@/lib/cn';

const MonacoEditor = dynamic(() => import('@monaco-editor/react').then((module) => {
  module.loader.config({ paths: { vs: '/monaco/vs' } });
  return module.default;
}), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center text-cream/40 text-xs">
      <Loader2 className="w-4 h-4 animate-spin mr-2" />Loading editor…
    </div>
  ),
});

export interface EditorTab {
  path: string;
  content: string;
}

function languageFor(path: string): string {
  if (path.endsWith('.ts') || path.endsWith('.tsx')) return 'typescript';
  if (path.endsWith('.js') || path.endsWith('.jsx')) return 'javascript';
  if (path.endsWith('.py')) return 'python';
  if (path.endsWith('.json')) return 'json';
  if (path.endsWith('.css')) return 'css';
  if (path.endsWith('.html')) return 'html';
  if (path.endsWith('.md')) return 'markdown';
  if (path.endsWith('.yml') || path.endsWith('.yaml')) return 'yaml';
  if (path.endsWith('.sql')) return 'sql';
  if (path.endsWith('.sh')) return 'shell';
  return 'plaintext';
}

interface Props {
  tabs: EditorTab[];
  activePath: string | null;
  loading?: boolean;
  mode?: 'approved' | 'diff';
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  emptyActions?: React.ReactNode;
  diffSlot?: React.ReactNode;
}

export function EditorPane({
  tabs,
  activePath,
  loading,
  mode = 'approved',
  onSelectTab,
  onCloseTab,
  emptyActions,
  diffSlot,
}: Props) {
  const active = tabs.find((t) => t.path === activePath) ?? null;
  const [cursor, setCursor] = useState({ line: 1, column: 1 });

  if (mode === 'diff' && diffSlot) {
    return <div className="h-full flex flex-col bg-[#101820]">{diffSlot}</div>;
  }

  if (tabs.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-[#101820] text-center px-6">
        <p className="font-hand text-xl text-gold">a quiet desk</p>
        <p className="text-lg font-semibold text-cream mt-1">No files yet</p>
        <p className="text-xs text-cream/50 mt-1 max-w-sm">
          Import an existing project to start, or ask RLB to create one.
        </p>
        {emptyActions && <div className="mt-5 flex flex-wrap items-center justify-center gap-2">{emptyActions}</div>}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#101820] min-w-0">
      <div className="flex items-center border-b border-cream/10 bg-[#121c24] overflow-x-auto shrink-0">
        {tabs.map((tab) => {
          const selected = tab.path === activePath;
          return (
            <div
              key={tab.path}
              className={cn(
                'group flex items-center gap-1.5 px-3 py-2 text-[11px] border-r border-cream/10 cursor-pointer shrink-0',
                selected ? 'bg-[#101820] text-cream' : 'text-cream/40 hover:text-cream/80',
              )}
            >
              <button type="button" onClick={() => onSelectTab(tab.path)} className="font-mono max-w-[160px] truncate">
                {tab.path.split('/').pop()}
                {selected && <span className="ml-1 text-gold">·</span>}
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onCloseTab(tab.path); }}
                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-paper/10"
                aria-label={`Close ${tab.path}`}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          );
        })}
        <span className="ml-auto px-3 text-[10px] font-mono text-cream/40 shrink-0">
          {active ? languageFor(active.path) : ''} · approved
        </span>
      </div>
      <div className="flex-1 min-h-0 relative">
        {active ? (
          <MonacoEditor
            height="100%"
            language={languageFor(active.path)}
            value={active.content}
            theme="vs-dark"
            onMount={(editor) => {
              editor.onDidChangeCursorPosition((event) => {
                setCursor({ line: event.position.lineNumber, column: event.position.column });
              });
            }}
            options={{
              readOnly: true,
              minimap: { enabled: true, scale: 2 },
              fontSize: 13,
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              padding: { top: 8 },
            }}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-xs text-cream/40">Select a file</div>
        )}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#101820]/70 text-cream/40 text-xs">
            <Loader2 className="w-4 h-4 animate-spin mr-2" />Reading file…
          </div>
        )}
      </div>
      <div className="h-7 shrink-0 border-t border-cream/10 bg-[#121c24] px-3 flex items-center justify-between text-[10px] text-cream/45 font-mono">
        <span>Ln {cursor.line}, Col {cursor.column}</span>
        <span>{active ? languageFor(active.path) : '—'}</span>
        <span>Prettier</span>
      </div>
    </div>
  );
}
