/** Client-side import helpers aligned with the existing ZIP/files backend contracts. */

export const MAX_ZIP_BYTES = 25 * 1024 * 1024;
export const MAX_IMPORT_UNCOMPRESSED_BYTES = 100 * 1024 * 1024;
export const MAX_IMPORT_FILE_COUNT = 5000;

export type ImportEntry = { file: File; relativePath: string };

export function isZipFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith('.zip') || file.type === 'application/zip' || file.type === 'application/x-zip-compressed';
}

export function normalizeRelativePath(path: string, fallbackName: string): string {
  const raw = (path || fallbackName || '').replace(/\\/g, '/').replace(/^\/+/, '');
  return raw.replace(/\/+/g, '/');
}

export function isSkippableImportPath(path: string): boolean {
  const parts = path.split('/').filter(Boolean);
  if (parts.length === 0) return true;
  if (parts.includes('__MACOSX')) return true;
  const name = parts[parts.length - 1];
  if (!name || name === '.' || name === '..') return true;
  if (name === '.DS_Store' || name === 'Thumbs.db' || name === 'desktop.ini') return true;
  if (name.startsWith('._')) return true;
  return false;
}

export function entriesFromFileList(list: FileList | File[]): ImportEntry[] {
  return Array.from(list).map((file) => ({
    file,
    relativePath: normalizeRelativePath(
      (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
      file.name,
    ),
  }));
}

export function sanitizeImportEntries(entries: ImportEntry[]): {
  entries: ImportEntry[];
  skipped: number;
} {
  const seen = new Set<string>();
  const cleaned: ImportEntry[] = [];
  let skipped = 0;

  for (const entry of entries) {
    const relativePath = normalizeRelativePath(entry.relativePath, entry.file.name);
    if (!relativePath || relativePath.endsWith('/')) {
      skipped += 1;
      continue;
    }
    if (isSkippableImportPath(relativePath)) {
      skipped += 1;
      continue;
    }
    if (seen.has(relativePath)) {
      skipped += 1;
      continue;
    }
    seen.add(relativePath);
    cleaned.push({ file: entry.file, relativePath });
  }

  return { entries: cleaned, skipped };
}

export function validateImportPayload(entries: ImportEntry[]): string | null {
  if (entries.length === 0) {
    return 'No importable files were selected. Choose project files or a .zip archive.';
  }
  if (entries.length > MAX_IMPORT_FILE_COUNT) {
    return `Import exceeds the ${MAX_IMPORT_FILE_COUNT} file limit.`;
  }
  const total = entries.reduce((sum, entry) => sum + (entry.file.size || 0), 0);
  if (total > MAX_IMPORT_UNCOMPRESSED_BYTES) {
    return 'Import exceeds the 100 MB uncompressed size quota.';
  }
  return null;
}

export function validateZipFile(file: File): string | null {
  if (!isZipFile(file)) {
    return 'Only .zip archives are supported (25 MB max).';
  }
  if (file.size > MAX_ZIP_BYTES) {
    return 'Archive exceeds maximum upload size of 25 MB.';
  }
  return null;
}
