const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { EventEmitter } = require('node:events');

function harness({ instanceLock = true, packaged = true } = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rlb-electron-test-'));
  const handlers = new Map();
  const children = [];
  const windows = [];
  const errors = [];
  const fetches = [];
  let ready;
  const app = new EventEmitter();
  Object.assign(app, {
    isPackaged: packaged,
    requestSingleInstanceLock: () => instanceLock,
    whenReady: () => ({ then: (callback) => { ready = callback; } }),
    quit: () => {}, exit: () => {},
    getPath: () => directory,
    getVersion: () => '0.1.0',
    setAppUserModelId: () => {},
    getLoginItemSettings: () => ({}), setLoginItemSettings: () => {},
  });
  class BrowserWindow extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.webContents = new EventEmitter();
      this.webContents.setWindowOpenHandler = () => {};
      this.isDestroyed = () => false; this.show = () => {}; this.focus = () => {}; this.hide = () => {};
      this.loadURL = (url) => { this.url = url; };
      windows.push(this);
    }
  }
  class Tray extends EventEmitter { setToolTip() {} setContextMenu() {} }
  const electron = {
    app, BrowserWindow, Tray,
    ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
    nativeImage: { createFromPath: (file) => { assert.ok(fs.existsSync(file)); return {}; } },
    Menu: { buildFromTemplate: (items) => items },
    dialog: { showErrorBox: (...args) => errors.push(args), showOpenDialog: async () => ({ canceled: false, filePaths: ['/selected/project'] }) },
    safeStorage: { isEncryptionAvailable: () => true, encryptString: (value) => Buffer.from(value), decryptString: (value) => value.toString() },
  };
  const spawn = (binary, args, options) => {
    const child = new EventEmitter();
    Object.assign(child, { stdout: new EventEmitter(), stderr: new EventEmitter(), exitCode: null, binary, args, options, pid: 100 + children.length });
    children.push(child); return child;
  };
  const context = {
    require: (name) => name === 'electron' ? electron : name === 'node:child_process' ? { spawn } : require(name),
    __dirname: path.resolve(__dirname, '..'),
    process: { ...process, resourcesPath: '/bundled-resources', env: { ...process.env, RLB_DEVICE_TOKEN: 'inherited-device-secret', CREDENTIAL_ENCRYPTION_KEY: 'inherited-key', GROQ_API_KEY: 'inherited-provider-secret' } },
    console, URL, Buffer, setTimeout, clearTimeout,
    fetch: async (url, options = {}) => {
      fetches.push({ url, options });
      if (url.endsWith('/api/v1/devices/pair')) return { ok: true, json: async () => ({ device_token: 'paired-secret', device: { id: 'device', name: 'PC', user_id: 'owner' } }) };
      return { ok: true, json: async () => ({}) };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../main.js'), 'utf8'), context);
  return { directory, app, children, windows, handlers, errors, fetches, ready: () => ready?.(), cleanup: () => fs.rmSync(directory, { recursive: true, force: true }) };
}

function trustedEvent(window) {
  return { sender: window.webContents, senderFrame: { url: window.url, isMainFrame: true } };
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
