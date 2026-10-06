const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');
const exportsObject = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/lib/workspaceRun.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: exportsObject });
const { runWorkspaceTask } = exportsObject;

function harness(task = null, activePath = 'hello.py') {
  const calls = [];
  return { calls, args: { task, activePath,
    createTask: async objective => calls.push(['create', objective]),
    resumeTask: async () => calls.push(['resume']),
    showDiff: () => calls.push(['review']),
  } };
}

test('Run on a fresh workspace creates a verification task without issuing a shell command', async () => {
  const { calls, args } = harness();
  assert.equal(await runWorkspaceTask(args), null);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'create');
  assert.match(calls[0][1], /"hello.py"/);
  assert.match(calls[0][1], /Do not skip approval gates/);
});
test('Run without a selected file explains the required objective and creates no task', async () => {
  const { calls, args } = harness(null, null);
  assert.match(await runWorkspaceTask(args), /Select a file/);
  assert.equal(calls.length, 0);
});
test('Run at human review gates never resumes or creates work', async () => {
  for (const status of ['plan_review', 'code_review']) {
    const { calls, args } = harness({ id: 'task', status });
    assert.match(await runWorkspaceTask(args), /Review/);
    assert.equal(calls.filter(([action]) => action !== 'review').length, 0);
    assert.equal(calls.length, status === 'code_review' ? 1 : 0);
  }
});
test('Run resumes active workflow stages through the durable queue', async () => {
  for (const status of ['ready', 'analyzing', 'planning', 'staging_setup', 'coding', 'test_planning', 'test_executing', 'repairing', 'reviewing']) {
    const { calls, args } = harness({ id: 'task', status });
    await runWorkspaceTask(args);
    assert.deepEqual(calls, [['resume']]);
  }
});
test('Run after a terminal task creates a fresh task rather than resuming terminal evidence', async () => {
  for (const status of ['completed', 'cancelled', 'failed']) {
    const { calls, args } = harness({ id: 'old-task', status });
    await runWorkspaceTask(args);
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], 'create');
  }
});
test('Run propagates runtime failures so the renderer can display them', async () => {
  const { args } = harness();
  args.createTask = async () => { throw new Error('Local project unavailable'); };
  await assert.rejects(runWorkspaceTask(args), /Local project unavailable/);
});
