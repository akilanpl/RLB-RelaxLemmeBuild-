const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const { FileMatcher } = require('app-builder-lib/out/fileMatcher');
const { build } = require('../package.json');

test('standalone assets have one copy owner even after packaged smoke populates them', () => {
  const base = path.resolve(__dirname, '..');
  const resources = build.extraResources;
  const standalone = resources.find(item => item.from === '../frontend/.next/standalone');
  const matcher = new FileMatcher(path.resolve(base, standalone.from),
    path.resolve(base, standalone.to), value => value, standalone.filter);
  const filter = matcher.createFilter();
  const fileStat = { isDirectory: () => false };
  for (const asset of ['public/monaco/vs/language/typescript/ts.worker.js', '.next/static/chunks/main.js']) {
    assert.equal(filter(path.join(matcher.from, asset), fileStat), false,
      `${asset} must not be copied by the broad standalone resource`);
  }
  for (const file of ['server.js', '.next/server/app/device-setup.html']) {
    assert.equal(filter(path.join(matcher.from, file), fileStat), true);
  }
  for (const [suffix, asset] of [
    ['/public', 'monaco/vs/language/typescript/ts.worker.js'],
    ['/.next/static', 'chunks/main.js'],
    ['/node_modules', 'next/dist/server/next-server.js'],
  ]) {
    const owners = resources.filter(item => item.to === `frontend/standalone${suffix}`);
    assert.equal(owners.length, 1);
    const owner = new FileMatcher(path.resolve(base, owners[0].from),
      path.resolve(base, owners[0].to), value => value, owners[0].filter || ['**/*']);
    assert.equal(owner.createFilter()(path.join(owner.from, asset), fileStat), true);
  }
});
