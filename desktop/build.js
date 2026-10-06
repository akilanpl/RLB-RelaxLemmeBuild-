const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

if (process.argv.includes('--windows-installer') && (process.platform !== 'win32' || process.arch !== 'x64')) {
  console.error('Build the Windows installer on Windows so the bundled Python sidecar matches its target.');
  process.exit(1);
}

const root = path.resolve(__dirname, '..');
const frontend = spawnSync('npm', ['run', 'build'], {
  cwd: path.join(root, 'frontend'),
  stdio: 'inherit',
  shell: process.platform === 'win32',
  env: { ...process.env, NEXT_PUBLIC_API_URL: 'http://127.0.0.1:8000',
    NEXT_PUBLIC_SUPABASE_URL: '', NEXT_PUBLIC_SUPABASE_ANON_KEY: '', NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: '',
    NEXT_PUBLIC_CONTROL_API_URL: process.env.RLB_RELEASE_CONTROL_PLANE_URL || '',
  },
});
if (frontend.status !== 0) process.exit(frontend.status || 1);

const venvPython = process.platform === 'win32'
  ? path.join(root, 'backend', '.venv', 'Scripts', 'python.exe')
  : path.join(root, 'backend', '.venv', 'bin', 'python');
const python = fs.existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3');
const backend = spawnSync(python, [
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
  '--name', 'rlb-runtime', '--paths', root, '--collect-submodules', 'backend.app',
  path.join(root, 'backend', 'desktop_runtime.py'),
], {
  cwd: root, stdio: 'inherit',
  env: { ...process.env, PYINSTALLER_CONFIG_DIR: path.join(root, 'build', '.pyinstaller-cache') },
});
if (backend.error) throw backend.error;
if (backend.status !== 0) process.exit(backend.status || 1);
// Never include development .env files traced into Next's standalone directory.
const standalone = path.join(root, 'frontend', '.next', 'standalone');
function stripEnvFiles(folder) {
  for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) stripEnvFiles(file);
    else if (entry.name === '.env' || entry.name.startsWith('.env.')) fs.rmSync(file);
  }
}
stripEnvFiles(standalone);
if (process.platform === 'win32') {
  const tools = spawnSync(python, [path.join(__dirname, 'bundle_toolchains.py')], { cwd: root, stdio: 'inherit' });
  if (tools.error) throw tools.error;
  if (tools.status !== 0) process.exit(tools.status || 1);
}
for (const file of [path.join(standalone, 'server.js'), path.join(root, 'dist', 'rlb-runtime', process.platform === 'win32' ? 'rlb-runtime.exe' : 'rlb-runtime')]) {
  if (!fs.existsSync(file)) throw new Error(`Release asset missing: ${file}`);
}
