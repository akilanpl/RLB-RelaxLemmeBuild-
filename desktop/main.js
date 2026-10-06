const { app, BrowserWindow, Tray, Menu, nativeImage, dialog, ipcMain, safeStorage } = require('electron');
const { spawn } = require('node:child_process');
const net = require('node:net');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

let window;
let tray;
let backend;
let frontend;
let quitting = false;
let frontendReady = false;
let localApiToken;
let deviceCredential;
let frontendToken;
let credentialEncryptionKey;
let runtimeInstanceId;
let startupComplete = false;
let recovery = Promise.resolve();
const restartAttempts = { backend: 0, frontend: 0 };

function childEnvironment() {
  if (development) return { ...process.env };
  const allowed = new Set(['PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
    'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'HOMEDRIVE', 'HOMEPATH',
    'TMP', 'TEMP', 'TMPDIR', 'LANG', 'LC_ALL']);
  return Object.fromEntries(Object.entries(process.env).filter(([key]) => allowed.has(key)));
}

const development = !app.isPackaged;
const repositoryRoot = path.resolve(__dirname, '..');
let runtimeUrl;
let backendPort;
let frontendPort;
let frontendUrl;
const logPath = () => path.join(app.getPath('userData'), 'logs', 'desktop.log');
const credentialPath = () => path.join(app.getPath('userData'), 'credentials', 'device-session.bin');

function readDeviceCredential() {
  const file = credentialPath();
  if (!fs.existsSync(file)) return null;
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Operating-system secure credential storage is unavailable.');
  const encrypted = fs.readFileSync(file);
  const credential = JSON.parse(safeStorage.decryptString(encrypted));
  if (typeof credential.controlPlaneUrl !== 'string' || typeof credential.deviceToken !== 'string') {
    throw new Error('The saved device credential is invalid.');
  }
  return credential;
}

function persistEncrypted(file, value) {
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Operating-system secure credential storage is unavailable.');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp`;
  const descriptor = fs.openSync(temporary, 'w', 0o600);
  try {
    fs.writeFileSync(descriptor, safeStorage.encryptString(value));
    fs.fsyncSync(descriptor);
  } finally { fs.closeSync(descriptor); }
  fs.renameSync(temporary, file);
}

function writeDeviceCredential(controlPlaneUrl, deviceToken, ownerId) {
  persistEncrypted(credentialPath(), JSON.stringify({ controlPlaneUrl, deviceToken, ownerId }));
}

function log(message) {
  const file = logPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, `${new Date().toISOString()} ${message}\n`);
}

function pipeLogs(child, label) {
  child.stdout?.on('data', (data) => log(`${label}: ${String(data).trimEnd()}`));
  child.stderr?.on('data', (data) => log(`${label}: ${String(data).trimEnd()}`));
  child.on('error', (error) => { child.spawnError = error; log(`${label} failed to start: ${error.message}`); });
  child.on('exit', (code, signal) => {
    if (child === frontend) frontendReady = false;
    if (!quitting) {
      log(`${label} exited unexpectedly (code=${code}, signal=${signal})`);
      if (startupComplete) recoverChild(label, child);
    }
  });
}

function assertTrustedDesktopRenderer(event) {
  let origin;
  try {
    origin = new URL(event.senderFrame?.url || '').origin;
  } catch {
    origin = '';
  }
  if (!frontendReady || !window || window.isDestroyed() ||
      event.sender !== window.webContents ||
      event.senderFrame !== window.webContents.mainFrame || origin !== frontendUrl) {
    throw new Error('Untrusted desktop renderer.');
  }
}

function startBackend() {
  const userData = app.getPath('userData');
  if (app.isPackaged && fs.existsSync(path.join(userData, 'config.env'))) {
    // Release settings are supplied by this process; never load development config.
    log('Desktop release ignores config.env; configure providers in the desktop UI.');
  }
  const env = {
    ...childEnvironment(),
    ENVIRONMENT: 'desktop',
    API_V1_PREFIX: '/api/v1',
    RLB_PARENT_PID: String(process.pid),
    RLB_RUNTIME_INSTANCE_ID: runtimeInstanceId,
    RLB_PROJECT_PYTHON: app.isPackaged && process.platform === 'win32' ? path.join(process.resourcesPath, 'toolchains', 'python', 'python.exe') : '',
    RLB_PROJECT_NODE_DIR: app.isPackaged && process.platform === 'win32' ? path.join(process.resourcesPath, 'toolchains', 'node') : '',
    DATABASE_URL: '',
    SUPABASE_SERVICE_ROLE_KEY: '',
    CREDENTIAL_ENCRYPTION_KEY: credentialEncryptionKey,
    RLB_LOCAL_OWNER_ID: deviceCredential?.ownerId || '',
    RUN_EMBEDDED_WORKER: 'true',
    RLB_CONTROL_PLANE_ONLY: 'false',
    DEBUG: 'false',
    RLB_DATA_DIR: path.join(userData, 'data'),
    LOCAL_DATA_DIR: path.join(userData, 'data'),
    RLB_ENV_FILE: app.isPackaged ? '' : path.join(userData, 'config.env'),
    PORT: String(backendPort),
    RLB_LOCAL_API_TOKEN: localApiToken,
    RLB_CONTROL_PLANE_URL: deviceCredential?.controlPlaneUrl || '',
    RLB_DEVICE_TOKEN: deviceCredential?.deviceToken || '',
    RLB_DESKTOP_ORIGIN: frontendUrl,
  };
  const options = {
    cwd: app.isPackaged ? userData : repositoryRoot,
    env,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  };
  if (app.isPackaged) {
    const binary = path.join(process.resourcesPath, 'backend', process.platform === 'win32' ? 'rlb-runtime.exe' : 'rlb-runtime');
    backend = spawn(binary, [], options);
  } else {
    const python = process.env.RLB_PYTHON ||
      path.join(repositoryRoot, 'backend', '.venv', 'bin', 'python');
    const fallback = process.platform === 'win32'
      ? path.join(repositoryRoot, 'backend', '.venv', 'Scripts', 'python.exe')
      : python;
    backend = spawn(fs.existsSync(fallback) ? fallback : 'python3', ['-m', 'backend.desktop_runtime'], options);
  }
  pipeLogs(backend, 'backend');
}

function startFrontend() {
  frontendReady = false;
  const env = childEnvironment();
  for (const key of [
    'RLB_DEVICE_TOKEN', 'RLB_LOCAL_API_TOKEN', 'RLB_DESKTOP_FRONTEND_TOKEN',
    'SUPABASE_SERVICE_ROLE_KEY', 'DATABASE_URL', 'CREDENTIAL_ENCRYPTION_KEY',
    'GROQ_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'DAYTONA_API_KEY',
  ]) {
    delete env[key];
  }
  if (!app.isPackaged) {
    frontend = spawn('npm', ['run', 'dev', '--', '--hostname', '127.0.0.1', '--port', String(frontendPort)], {
      cwd: path.join(repositoryRoot, 'frontend'),
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: process.platform === 'win32',
      env: {
        ...env,
        NEXT_PUBLIC_API_URL: runtimeUrl,
        RLB_DESKTOP_FRONTEND_TOKEN: frontendToken,
      },
    });
  } else {
    const server = path.join(process.resourcesPath, 'frontend', 'standalone', 'server.js');
    frontend = spawn(process.execPath, [path.join(process.resourcesPath, 'frontend-entry.js'), server], {
      cwd: path.dirname(server),
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...env,
        ELECTRON_RUN_AS_NODE: '1',
        RLB_PARENT_PID: String(process.pid),
        HOSTNAME: '127.0.0.1',
        PORT: String(frontendPort),
        NEXT_PUBLIC_API_URL: runtimeUrl,
        RLB_DESKTOP_FRONTEND_TOKEN: frontendToken,
      },
    });
  }
  pipeLogs(frontend, 'frontend');
}

async function findAvailablePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function waitFor(url, child, label, headers = {}, verify = () => true) {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    if (quitting) throw new Error("Desktop is shutting down.");
    if (child.spawnError) throw child.spawnError;
    if (child.exitCode !== null || child.signalCode) throw new Error(`${label} stopped before becoming ready.`);
    try {
      const response = await fetch(url, { headers, signal: AbortSignal.timeout(2000) });
      if (response.ok && await verify(response)) return;
    } catch {
      // The process is still starting; retry until the bounded startup deadline.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${label} did not become ready within 60 seconds.`);
}

function createWindow() {
  window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 360,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  window.webContents.on('will-navigate', (event, target) => {
    try {
      if (new URL(target).origin !== frontendUrl) event.preventDefault();
    } catch { event.preventDefault(); }
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.loadURL(deviceCredential?.ownerId ? `${frontendUrl}/dashboard` : `${frontendUrl}/device-setup`);
  window.on('session-end', () => app.quit());
  window.on('query-session-end', () => app.quit());
  window.on('close', (event) => {
    if (!quitting) {
      event.preventDefault();
      window.hide();
    }
  });
}

function stopProcess(child, graceful = false) {
  if (!child || child.exitCode !== null || child.signalCode || child.spawnError) return Promise.resolve();
  return new Promise((resolve) => {
    let forceTimer;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(forceTimer);
      resolve();
    };
    child.once('exit', finish);
    forceTimer = setTimeout(() => {
      if (process.platform === 'win32') {
        const force = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
        force.on('error', () => child.kill());
        force.once('exit', () => { if (child.exitCode === null) child.kill(); });
      } else { child.kill('SIGKILL'); }
    }, graceful ? 30000 : 10000);
    if (graceful) {
      fetch(`${runtimeUrl}/api/v1/desktop/shutdown`, {
        method: 'POST', headers: { 'X-RLB-Local-Token': localApiToken }, signal: AbortSignal.timeout(2000),
      }).catch((error) => log(`Runtime shutdown request failed: ${error.message}`));
    } else { child.kill('SIGTERM'); }
  });
}

async function waitForBackend() {
  await waitFor(`${runtimeUrl}/api/v1/desktop/status`, backend, 'Local runtime',
    { 'X-RLB-Local-Token': localApiToken }, async (response) => {
      const status = await response.json();
      return status.instance_id === runtimeInstanceId && status.worker_ready === true;
    });
}

function recoverChild(label, failed) {
  recovery = recovery.then(async () => {
    if (quitting || failed !== (label === 'backend' ? backend : frontend)) return;
    if (++restartAttempts[label] > 2) throw new Error(`${label} repeatedly stopped. Reopen RLB to recover persisted work.`);
    log(`Restarting ${label} from persisted state.`);
    if (label === 'backend') {
      startBackend();
      await waitForBackend();
    } else {
      startFrontend();
      await waitFor(`${frontendUrl}/api/desktop-ready`, frontend, 'Desktop frontend', {
        'X-RLB-Desktop-Nonce': frontendToken,
      });
      frontendReady = true;
    }
    if (!quitting && window && !window.isDestroyed()) window.webContents.reload();
  }).catch((error) => {
    if (quitting) return;
    log(`Runtime recovery failed: ${error.message}`);
    dialog.showErrorBox('RLB runtime stopped', error.message);
    app.quit();
  });
}

function showTrayMenu() {
  const settings = app.getLoginItemSettings();
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open RLB', click: () => { window.show(); window.focus(); } },
    { type: 'separator' },
    {
      label: 'Start with Windows',
      type: 'checkbox',
      checked: settings.openAtLogin,
      click: (item) => app.setLoginItemSettings({ openAtLogin: item.checked, name: 'RLB' }),
    },
    { label: 'Quit RLB and stop runtime', click: () => app.quit() },
  ]));
}

const installerShutdown = process.argv.includes('--quit-for-update');
const hasInstanceLock = app.requestSingleInstanceLock();
if (!hasInstanceLock || installerShutdown) {
  app.quit();
} else {
  app.on('second-instance', (_event, argv) => {
    if (argv.includes('--quit-for-update')) app.quit();
    else { window?.show(); window?.focus(); }
  });
}

if (hasInstanceLock && !installerShutdown) app.whenReady().then(async () => {
  app.setAppUserModelId('com.rlb.desktop');
  localApiToken = randomBytes(32).toString('base64url');
  runtimeInstanceId = randomBytes(32).toString('base64url');
  ipcMain.handle('get-runtime-url', (event) => {
    assertTrustedDesktopRenderer(event);
    return runtimeUrl;
  });
  ipcMain.handle('get-local-identity', (event) => {
    assertTrustedDesktopRenderer(event);
    return deviceCredential?.ownerId ? { userId: deviceCredential.ownerId } : null;
  });
  ipcMain.handle('get-local-api-token' , (event) => {
    assertTrustedDesktopRenderer(event);
    return localApiToken;
  });
  ipcMain.handle('select-local-folder', async (event) => {
    assertTrustedDesktopRenderer(event);
    const result = await dialog.showOpenDialog(window, {
      title: 'Choose a local project folder',
      properties: ['openDirectory'],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle('pair-device', async (event, request) => {
    assertTrustedDesktopRenderer(event);
    const controlUrl = new URL(String(request.controlPlaneUrl));
    if (controlUrl.username || controlUrl.password || controlUrl.pathname !== '/' || controlUrl.search || controlUrl.hash) {
      throw new Error('The control plane must be an origin without credentials or a path.');
    }
    if (controlUrl.protocol !== 'https:' &&
        !(controlUrl.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(controlUrl.hostname))) {
      throw new Error('The control plane must use HTTPS.');
    }
    const pairingResponse = await fetch(`${controlUrl.origin}/api/v1/devices/pair`, {
      method: 'POST',
      redirect: 'error',
      signal: AbortSignal.timeout(15000),
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        pairing_token: String(request.pairingToken),
        name: String(request.name || 'RLB Windows device'),
        platform: process.platform,
        architecture: process.arch,
        app_version: app.getVersion(),
        runtime_version: app.getVersion(),
        capabilities: { local_execution: true, remote_commands: true },
      }),
    });
    const pairingResult = await pairingResponse.json();
    if (!pairingResponse.ok) {
      throw new Error(pairingResult.detail || 'The pairing token was rejected.');
    }
    if (typeof pairingResult.device_token !== 'string' ||
        typeof pairingResult.device?.id !== 'string' ||
        typeof pairingResult.device?.name !== 'string' ||
        typeof pairingResult.device?.user_id !== 'string') {
      throw new Error('The control plane returned an invalid pairing response.');
    }
    const configuredResponse = await fetch(`${runtimeUrl}/api/v1/device-session/configure`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-RLB-Local-Token': localApiToken,
      },
      signal: AbortSignal.timeout(15000),
      body: JSON.stringify({
        control_plane_url: controlUrl.origin,
        device_token: pairingResult.device_token,
        owner_id: pairingResult.device.user_id,
      }),
    });
    if (!configuredResponse.ok) {
      const result = await configuredResponse.json().catch(() => ({}));
      throw new Error(result.detail || 'The local runtime could not start the device connection.');
    }
    writeDeviceCredential(controlUrl.origin, pairingResult.device_token, pairingResult.device.user_id);
    deviceCredential = {
      controlPlaneUrl: controlUrl.origin,
      deviceToken: pairingResult.device_token,
      ownerId: pairingResult.device.user_id,
    };
    return { id: pairingResult.device.id, name: pairingResult.device.name };
  });

  try {
    deviceCredential = readDeviceCredential();
    if (!safeStorage.isEncryptionAvailable()) throw new Error('Operating-system secure storage is required.');
    const keyFile = path.join(app.getPath('userData'), 'credentials', 'provider-key.bin');
    if (fs.existsSync(keyFile)) {
      credentialEncryptionKey = safeStorage.decryptString(fs.readFileSync(keyFile));
    } else {
      credentialEncryptionKey = randomBytes(32).toString('base64url');
      persistEncrypted(keyFile, credentialEncryptionKey);
    }
  } catch (error) {
    log(`Could not unlock device credentials: ${error.message}`);
    dialog.showErrorBox('RLB device credentials unavailable', error.message);
    app.quit();
    return;
  }

  try {
    backendPort = await findAvailablePort();
    runtimeUrl = `http://127.0.0.1:${backendPort}`;
    frontendPort = await findAvailablePort();
    frontendUrl = `http://127.0.0.1:${frontendPort}`;
    frontendToken = randomBytes(32).toString('base64url');
    startBackend();
    await waitForBackend();
    startFrontend();
    await waitFor(`${frontendUrl}/api/desktop-ready`, frontend, 'Desktop frontend', {
      'X-RLB-Desktop-Nonce': frontendToken,
    });
    if (frontend.exitCode !== null || frontend.signalCode) throw new Error('Desktop frontend stopped before becoming ready.');
    frontendReady = true;
    createWindow();
    tray = new Tray(nativeImage.createFromPath(path.join(__dirname, 'tray.png')));
    tray.setToolTip('RLB');
    tray.on('click', () => { window.show(); window.focus(); });
    showTrayMenu();
    startupComplete = true;
    log(`Desktop ready: runtime=${runtimeUrl}, frontend=${frontendUrl}`);
    app.on('activate', () => window?.show());
  } catch (error) {
    log(`Desktop startup failed: ${error.stack || error.message}`);
    dialog.showErrorBox('RLB could not start', error.message);
    app.quit();
  }
});

app.on('before-quit', (event) => {
  if (quitting) return;
  quitting = true;
  event.preventDefault();
  Promise.all([stopProcess(frontend), stopProcess(backend, true)])
    .then(() => app.quit())
    .catch((error) => {
      log(`Could not stop runtime cleanly: ${error.message}`);
      app.exit(1);
    });
});
