const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { EventEmitter } = require('node:events');

function harness({ instanceLock = true, packaged = true, configureFails = false, secureStorage = true } = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rlb-electron-test-'));
  const handlers = new Map();
  const children = [];
  const windows = [];
  const errors = [];
  const fetches = [];
  const trays = [];
  let quits = 0;
  let ready;
  const app = new EventEmitter();
  Object.assign(app, {
    isPackaged: packaged,
    requestSingleInstanceLock: () => instanceLock,
    whenReady: () => ({ then: (callback) => { ready = callback; } }),
    quit: () => { quits++; }, exit: () => {},
    getPath: () => directory,
    getVersion: () => '0.1.0',
    setAppUserModelId: () => {},
    getLoginItemSettings: () => ({}), setLoginItemSettings: () => {},
  });
  class BrowserWindow extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.webContents = new EventEmitter();
      this.webContents.mainFrame = { url: '', parent: null };
      this.webContents.setWindowOpenHandler = () => {};
      this.webContents.reload = () => { this.reloads = (this.reloads || 0) + 1; };
      this.isDestroyed = () => false; this.show = () => {}; this.focus = () => {}; this.hide = () => {};
      this.loadURL = (url) => { this.url = url; this.webContents.mainFrame.url = url; };
      windows.push(this);
    }
  }
  class Tray extends EventEmitter { constructor() { super(); trays.push(this); } setToolTip() {} setContextMenu(items) { this.items = items; } }
  const electron = {
    app, BrowserWindow, Tray,
    ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
    nativeImage: { createFromPath: (file) => { assert.ok(fs.existsSync(file)); return {}; } },
    Menu: { buildFromTemplate: (items) => items },
    dialog: { showErrorBox: (...args) => errors.push(args), showOpenDialog: async () => ({ canceled: false, filePaths: ['/selected/project'] }) },
    safeStorage: { isEncryptionAvailable: () => secureStorage, encryptString: (value) => Buffer.from(value), decryptString: (value) => value.toString() },
  };
  const spawn = (binary, args, options) => {
    const child = new EventEmitter();
    Object.assign(child, { stdout: new EventEmitter(), stderr: new EventEmitter(), exitCode: null, binary, args, options, pid: 100 + children.length });
    child.kill = () => { child.exitCode = 0; child.emit('exit', 0); };
    children.push(child); return child;
  };
  const context = {
    require: (name) => name === 'electron' ? electron : name === 'node:child_process' ? { spawn } : require(name),
    __dirname: path.resolve(__dirname, '..'),
    process: { ...process, resourcesPath: '/bundled-resources', env: { ...process.env, RLB_DEVICE_TOKEN: 'inherited-device-secret', CREDENTIAL_ENCRYPTION_KEY: 'inherited-key', GROQ_API_KEY: 'inherited-provider-secret' } },
    console, URL, Buffer, AbortSignal, setTimeout, clearTimeout,
    fetch: async (url, options = {}) => {
      fetches.push({ url, options });
      if (url.endsWith('/api/v1/devices/pair')) return { ok: true, json: async () => ({ device_token: 'paired-secret', device: { id: 'device', name: 'PC', user_id: 'owner' } }) };
      if (url.endsWith('/api/v1/desktop/status')) return { ok: true, json: async () => ({
        instance_id: children.filter(child => child.options.env.ENVIRONMENT === 'desktop').at(-1).options.env.RLB_RUNTIME_INSTANCE_ID,
        worker_ready: true,
      }) };
      if (url.endsWith('/device-session/configure') && configureFails) return { ok: false, json: async () => ({ detail: 'Rejected owner' }) };
      if (url.endsWith('/desktop/shutdown')) {
        const child = children.filter(child => child.options.env.ENVIRONMENT === 'desktop').at(-1);
        child.kill();
      }
      return { ok: true, json: async () => ({}) };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../main.js'), 'utf8'), context);
  return { directory, app, children, windows, handlers, errors, fetches, trays, quits: () => quits, ready: () => ready?.(), cleanup: () => fs.rmSync(directory, { recursive: true, force: true }) };
}

function trustedEvent(window) {
  return { sender: window.webContents, senderFrame: window.webContents.mainFrame };
}

test('packaged startup uses isolated ports, protected settings, nonce, and sandboxed renderer', async () => {
  const h = harness();
  try {
    await h.ready();
    assert.deepEqual(h.errors, []);
    assert.equal(h.children.length, 2);
    const [backend, frontend] = h.children;
    assert.equal(backend.options.env.ENVIRONMENT, 'desktop');
    assert.equal(backend.options.env.DATABASE_URL, '');
    assert.equal(backend.options.env.SUPABASE_SERVICE_ROLE_KEY, '');
    assert.equal(backend.options.env.DEBUG, 'false');
    assert.notEqual(backend.options.env.CREDENTIAL_ENCRYPTION_KEY, 'inherited-key');
    assert.notEqual(backend.options.env.PORT, frontend.options.env.PORT);
    assert.equal(frontend.options.env.RLB_LOCAL_API_TOKEN, undefined);
    assert.equal(frontend.options.env.GROQ_API_KEY, undefined);
    assert.equal(frontend.options.env.CREDENTIAL_ENCRYPTION_KEY, undefined);
    assert.ok(h.fetches.some(({ options }) => options.headers?.['X-RLB-Desktop-Nonce']));
    const window = h.windows[0];
    assert.equal(window.options.webPreferences.sandbox, true);
    assert.equal(window.options.webPreferences.nodeIntegration, false);
    assert.ok(window.url.endsWith('/device-setup'));
    const event = trustedEvent(window);
    assert.equal(h.handlers.get('get-local-api-token')(event), backend.options.env.RLB_LOCAL_API_TOKEN);
    assert.equal(h.handlers.get('get-runtime-url')(event), `http://127.0.0.1:${backend.options.env.PORT}`);
    assert.throws(() => h.handlers.get('get-local-api-token')({ sender: window.webContents, senderFrame: { url: 'https://evil.test', isMainFrame: true } }), /Untrusted/);
    await h.handlers.get('pair-device')(event, { controlPlaneUrl: 'https://control.test', pairingToken: 'one-time', name: 'PC' });
    assert.equal(h.handlers.get('get-local-identity')(event).userId, 'owner');
    const configured = h.fetches.find(({ url }) => url.endsWith('/device-session/configure'));
    assert.equal(configured.options.headers['X-RLB-Local-Token'], backend.options.env.RLB_LOCAL_API_TOKEN);
    assert.equal(JSON.parse(configured.options.body).owner_id, 'owner');
  } finally { h.cleanup(); }
});

test('second instance cannot start another runtime', async () => {
  const h = harness({ instanceLock: false });
  try { await h.ready(); assert.equal(h.children.length, 0); } finally { h.cleanup(); }
});


test('closing hides the window while runtime remains active; quit authenticates clean shutdown', async () => {
  const h = harness();
  try {
    await h.ready();
    let hidden = false;
    h.windows[0].hide = () => { hidden = true; };
    let prevented = false;
    h.windows[0].emit('close', { preventDefault: () => { prevented = true; } });
    assert.ok(hidden && prevented);
    assert.ok(h.children.every(child => child.exitCode === null));
    assert.ok(h.trays[0].items.some(item => item.label === 'Quit RLB and stop runtime'));
    h.app.emit('before-quit', { preventDefault() {} });
    await new Promise(resolve => setImmediate(resolve));
    const shutdown = h.fetches.find(({url}) => url.endsWith('/desktop/shutdown'));
    assert.ok(shutdown);
    assert.equal(shutdown.options.method, 'POST');
    assert.equal(shutdown.options.headers['X-RLB-Local-Token'], h.children[0].options.env.RLB_LOCAL_API_TOKEN);
    assert.ok(h.children.every(child => child.exitCode === 0));
  } finally { h.cleanup(); }
});

test('child failure restarts persisted runtime and reloads the UI', async () => {
  const h = harness();
  try {
    await h.ready();
    h.children[0].exitCode = 1;
    h.children[0].emit('exit', 1);
    await new Promise(resolve => setTimeout(resolve, 50));
    assert.equal(h.children.length, 3);
    assert.equal(h.children[2].options.env.LOCAL_DATA_DIR, h.children[0].options.env.LOCAL_DATA_DIR);
    assert.equal(h.children[2].options.env.CREDENTIAL_ENCRYPTION_KEY, h.children[0].options.env.CREDENTIAL_ENCRYPTION_KEY);
    assert.equal(h.windows[0].reloads, 1);
  } finally { h.cleanup(); }
});

test('failed local pairing verification never persists an enrollment', async () => {
  const h = harness({ configureFails: true });
  try {
    await h.ready();
    await assert.rejects(h.handlers.get('pair-device')(trustedEvent(h.windows[0]), {
      controlPlaneUrl: 'https://control.test', pairingToken: 'one-time',
    }), /Rejected owner/);
    assert.ok(!fs.existsSync(path.join(h.directory, 'credentials/device-session.bin')));
    assert.equal(h.handlers.get('get-local-identity')(trustedEvent(h.windows[0])), null);
  } finally { h.cleanup(); }
});

test('unavailable OS credential storage fails closed before processes start', async () => {
  const h = harness({ secureStorage: false });
  try {
    await h.ready();
    assert.equal(h.children.length, 0);
    assert.equal(h.errors.length, 1);
    assert.equal(h.quits(), 1);
  } finally { h.cleanup(); }
});


test('installer shutdown request goes to the existing app without starting another runtime', async () => {
  const h = harness();
  try {
    await h.ready();
    h.app.emit('second-instance', {}, ['RLB.exe', '--quit-for-update']);
    assert.equal(h.quits(), 1);
    assert.equal(h.children.length, 2);
  } finally { h.cleanup(); }
});


test('same-origin subframes cannot obtain the local runtime token', async () => {
  const h = harness();
  try {
    await h.ready();
    const window = h.windows[0];
    assert.throws(() => h.handlers.get('get-local-api-token')({
      sender: window.webContents, senderFrame: { url: window.url, parent: window.webContents.mainFrame },
    }), /Untrusted/);
  } finally { h.cleanup(); }
});


test('quit handles a child that already exited by signal without waiting forever', async () => {
  const h = harness();
  try {
    await h.ready();
    h.children[1].signalCode = 'SIGTERM';
    h.app.emit('before-quit', { preventDefault() {} });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.quits(), 1);
    assert.equal(h.children[0].exitCode, 0);
  } finally { h.cleanup(); }
});
