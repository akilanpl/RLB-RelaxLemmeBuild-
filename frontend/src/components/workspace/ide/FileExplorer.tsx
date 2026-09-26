'use client';

import React, { useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  FileCode,
  FileText,
  Folder,
  FolderOpen,
  GitBranch,
  Plus,
  RefreshCw,
  Search,
  Upload,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { entriesFromFileList } from '@/lib/importFiles';

export interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  sizeBytes?: number;
  children: Record<string, FileNode>;
}

export function buildFileTree(files: Array<{ relative_path?: string; relativePath?: string; size_bytes?: number }>): FileNode {
  const root: FileNode = { name: '', path: '', isDir: true, children: {} };
  for (const f of files) {
    const relPath = f.relative_path || f.relativePath;
    if (!relPath) continue;
    const parts = relPath.split('/');
    let current = root;
    parts.forEach((part, idx) => {
      const isLast = idx === parts.length - 1;
      const currentPath = parts.slice(0, idx + 1).join('/');
      if (!current.children[part]) {
        current.children[part] = {
          name: part,
          path: currentPath,
          isDir: !isLast,
          sizeBytes: isLast ? f.size_bytes : undefined,
          children: {},
        };
      }
      current = current.children[part];
    });
  }
  return root;
}

interface Props {
  files: Array<{ relative_path?: string; relativePath?: string; size_bytes?: number }>;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRefresh: () => void;
  onImportZip: (file: File) => void;
  onImportFiles: (entries: Array<{ file: File; relativePath: string }>) => void;
  importing?: boolean;
  gitRemoteUrl?: string | null;
}

export function FileExplorer({
  files,
  selectedPath,
  onSelect,
  onRefresh,
  onImportZip,
  onImportFiles,
  importing,
  gitRemoteUrl,
}: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const tree = useMemo(() => buildFileTree(files), [files]);
  const zipRef = React.useRef<HTMLInputElement>(null);
  const filesRef = React.useRef<HTMLInputElement>(null);
  const folderRef = React.useRef<HTMLInputElement>(null);

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const matchesFilter = (node: FileNode): boolean => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    if (node.path.toLowerCase().includes(q) || node.name.toLowerCase().includes(q)) return true;
    return Object.values(node.children).some(matchesFilter);
  };

  const renderTree = (node: FileNode, depth = 0): React.ReactNode => {
    const keys = Object.keys(node.children)
      .filter((key) => matchesFilter(node.children[key]))
      .sort((a, b) => {
        const A = node.children[a];
        const B = node.children[b];
        if (A.isDir && !B.isDir) return -1;
        if (!A.isDir && B.isDir) return 1;
        return a.localeCompare(b);
      });

    return keys.map((key) => {
      const child = node.children[key];
      const isExpanded = expanded.has(child.path) || Boolean(filter.trim());
      if (child.isDir) {
        return (
          <div key={child.path}>
            <button
              type="button"
              onClick={() => toggle(child.path)}
              style={{ paddingLeft: `${depth * 12 + 8}px` }}
              className="w-full flex items-center gap-1.5 py-1 text-left text-xs text-cream/80 hover:bg-paper/5 rounded-lg"
            >
              {isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-cream/40" /> : <ChevronRight className="w-3.5 h-3.5 text-cream/40" />}
              {isExpanded ? <FolderOpen className="w-3.5 h-3.5 text-skyblue" /> : <Folder className="w-3.5 h-3.5 text-skyblue" />}
              <span className="truncate">{child.name}</span>
            </button>
            {isExpanded && renderTree(child, depth + 1)}
          </div>
        );
      }
      const selected = selectedPath === child.path;
      return (
        <button
          key={child.path}
          type="button"
          onClick={() => onSelect(child.path)}
          style={{ paddingLeft: `${depth * 12 + 24}px` }}
          className={cn(
            'w-full flex items-center gap-1.5 py-1 text-left text-xs rounded-lg',
            selected ? 'bg-gold/15 text-gold' : 'text-cream/55 hover:bg-paper/5 hover:text-cream',
          )}
        >
          <FileText className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">{child.name}</span>
        </button>
      );
    });
  };

  return (
    <div className="h-full flex flex-col bg-[#121c24] border-r border-cream/10">
      <div className="h-10 px-3 flex items-center justify-between border-b border-cream/10">
        <span className="text-[10px] font-semibold tracking-widest text-cream/40">EXPLORER</span>
        <div className="flex items-center gap-1 relative">
          <button type="button" onClick={onRefresh} className="p-1 rounded-lg text-cream/40 hover:text-cream hover:bg-paper/10" title="Refresh" aria-label="Refresh files">
            <RefreshCw className={`w-3.5 h-3.5 ${importing ? 'animate-spin' : ''}`} />
          </button>
          <button type="button" onClick={() => setMenuOpen((v) => !v)} className="p-1 rounded-lg text-cream/40 hover:text-cream hover:bg-paper/10" title="Add" aria-label="Add files">
            <Plus className="w-3.5 h-3.5" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-7 z-20 w-44 rounded-2xl border border-cream/10 bg-[#1a2730] shadow-float py-1 text-xs text-cream">
              <button type="button" className="w-full px-3 py-2 text-left hover:bg-paper/10 flex items-center gap-2" onClick={() => { zipRef.current?.click(); setMenuOpen(false); }}>
                <Upload className="w-3.5 h-3.5" /> Upload ZIP
              </button>
              <button type="button" className="w-full px-3 py-2 text-left hover:bg-paper/10 flex items-center gap-2" onClick={() => { filesRef.current?.click(); setMenuOpen(false); }}>
                <FileCode className="w-3.5 h-3.5" /> Upload Files
              </button>
              <button type="button" className="w-full px-3 py-2 text-left hover:bg-paper/10 flex items-center gap-2" onClick={() => { folderRef.current?.click(); setMenuOpen(false); }}>
                <Folder className="w-3.5 h-3.5" /> Upload Folder
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="px-2 py-2 border-b border-cream/10">
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2 top-2.5 text-cream/30" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search"
            aria-label="Search files"
            className="w-full rounded-full bg-[#0e161c] border border-cream/10 pl-7 pr-3 py-1.5 text-xs text-cream outline-none focus:border-gold/40"
          />
        </div>
      </div>
      <div className="flex-1 overflow-auto p-1">
        {files.length === 0 ? (
          <div className="px-3 py-4 space-y-2">
            <p className="text-[11px] text-cream/40">No files yet. Import a ZIP or files into this empty workspace.</p>
            <button type="button" className="w-full rounded-full bg-coral/90 px-3 py-1.5 text-[11px] font-semibold text-paper" onClick={() => zipRef.current?.click()}>
              Upload ZIP
            </button>
            <button type="button" className="w-full rounded-full border border-cream/15 px-3 py-1.5 text-[11px] text-cream/80" onClick={() => filesRef.current?.click()}>
              Add files
            </button>
          </div>
        ) : (
          renderTree(tree)
        )}
      </div>
      <div className="border-t border-cream/10 px-3 py-3">
        <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold tracking-widest text-cream/40">
          <GitBranch className="h-3 w-3" /> GIT
        </p>
        <p className="truncate text-[11px] text-cream/55">
          {gitRemoteUrl || 'No remote connected'}
        </p>
        <p className="mt-1 text-[10px] text-cream/35">main · canonical</p>
      </div>
      <input ref={zipRef} type="file" accept=".zip,application/zip" className="hidden" aria-hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onImportZip(f); e.target.value = ''; }} />
      <input ref={filesRef} type="file" multiple className="hidden" aria-hidden onChange={(e) => {
        onImportFiles(entriesFromFileList(e.target.files || []));
        e.target.value = '';
      }} />
      <input
        ref={folderRef}
        type="file"
        multiple
        className="hidden"
        aria-hidden
        // @ts-expect-error webkitdirectory is supported in Chromium
        webkitdirectory=""
        onChange={(e) => {
          onImportFiles(entriesFromFileList(e.target.files || []));
          e.target.value = '';
        }}
      />
    </div>
  );
}
