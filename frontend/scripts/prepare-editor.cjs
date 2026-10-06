// Serve the existing Monaco runtime locally instead of depending on a CDN.
const fs = require('node:fs');
const path = require('node:path');
const source = path.resolve(path.dirname(require.resolve('monaco-editor')), '../..');
const target = path.resolve(__dirname, '../public/monaco');
fs.rmSync(target, { recursive: true, force: true });
fs.mkdirSync(target, { recursive: true });
fs.cpSync(path.join(source, 'min/vs'), path.join(target, 'vs'), { recursive: true });
fs.copyFileSync(path.join(source, 'LICENSE'), path.join(target, 'LICENSE'));
