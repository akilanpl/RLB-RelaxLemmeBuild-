const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

if (process.argv.includes('--windows-installer') && process.platform !== 'win32') {
  console.error('Build the Windows installer on Windows so the bundled Python sidecar matches its target.');
  process.exit(1);
}

const root = path.resolve(__dirname, '..');
const frontend = spawnSync('npm', ['run', 'build'], {
  cwd: path.join(root, 'frontend'),
  stdio: 'inherit',
  shell: process.platform === 'win32',
  env: { ...process.env, NEXT_PUBLIC_API_URL: 'http://127.0.0.1:8000' },
});
if (frontend.status !== 0) process.exit(frontend.status || 1);

const venvPython = process.platform === 'win32'
  ? path.join(root, 'backend', '.venv', 'Scripts', 'python.exe')
  : path.join(root, 'backend', '.venv', 'bin', 'python');
const python = fs.existsSync(venvPython) ? venvPython : 'python3';
const backend = spawnSync(python, [
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
  '--name', 'rlb-runtime', '--paths', root, '--collect-submodules', 'backend.app',
  path.join(root, 'backend', 'desktop_runtime.py'),
], {
  cwd: root, stdio: 'inherit',
  env: { ...process.env, PYINSTALLER_CONFIG_DIR: path.join(root, 'build', '.pyinstaller-cache') },
});
if (backend.error) throw backend.error;
process.exitCode = backend.status ?? 1;
