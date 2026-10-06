// Execute Next's standalone server in Electron's bundled Node runtime.
// Do not leave an orphaned server when Electron is killed or Windows logs out.
const path = require('node:path');
const parentPid = Number(process.env.RLB_PARENT_PID);
function parentAlive() {
  if (!Number.isSafeInteger(parentPid) || parentPid <= 0) throw new Error('A desktop parent is required.');
  try { process.kill(parentPid, 0); return true; } catch (error) {
    if (error.code === 'EPERM') return true;
    return false;
  }
}
if (!parentAlive()) process.exit(0);
const watcher = setInterval(() => { if (!parentAlive()) process.exit(0); }, 500);
watcher.unref();
require(path.resolve(process.argv[2]));
