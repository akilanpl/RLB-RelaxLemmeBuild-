const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function load(file, extra = {}) {
  const output = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(output, { exports, process: { env: {} }, FormData, console, ...extra });
  return exports;
}

test('desktop approval sends backend plan contract without requesting cloud auth', async () => {
  let cloudRequests = 0;
  let sent;
  const { apiClient } = load('lib/api.ts', {
    window: { rlbDesktop: {
      getLocalApiToken: async () => 'protected-token', getRuntimeUrl: async () => 'http://127.0.0.1:12345',
    } },
    require: () => { cloudRequests++; throw new Error('Cloud offline'); },
    fetch: async (url, options) => {
      sent = { url, options };
      return { ok: true, text: async () => '{}' };
    },
  });
  await apiClient.submitPlanApproval('task', 'approved');
  assert.equal(sent.url, 'http://127.0.0.1:12345/api/v1/tasks/task/approvals');
  assert.equal(JSON.parse(sent.options.body).approval_type, 'plan');
  assert.equal(sent.options.headers['X-RLB-Local-Token'], 'protected-token');
  assert.equal(cloudRequests, 0);
});

test('desktop workspace loading uses local authority while cloud is offline', async () => {
  let cloudRequests = 0;
  const auth = load('lib/auth.ts', {
    window: { rlbDesktop: {} },
    require: name => {
      if (name === './supabase') return { isSupabaseConfigured: true, getSupabaseClient: () => { cloudRequests++; throw new Error('Cloud offline'); } };
      if (name === '@/lib/api') return { apiClient: { listWorkspaces: async user => [user] } };
      throw new Error('Unexpected import: ' + name);
    },
  });
  assert.deepEqual(Array.from(await auth.fetchUserWorkspaces('paired-owner')), ['paired-owner']);
  assert.equal(cloudRequests, 0);
});
