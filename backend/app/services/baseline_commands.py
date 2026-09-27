"""Discover project checks without running project code on the API/worker host."""
import json
import posixpath
import shlex
from backend.app.models.test import BaselineCheckType as Check


async def discover_baseline_commands(storage, root):
    paths = await storage.list_files(root)
    prefix = root.rstrip('/') + '/'
    relative = {path[len(prefix):] for path in paths if path.startswith(prefix)}
    commands = {check: [] for check in Check}
    for manifest in sorted(path for path in relative if path.endswith('package.json') and path.count('/') <= 1):
        data = json.loads((await storage.read_file(prefix + manifest)).decode())
        folder = posixpath.dirname(manifest) or '.'
        shell_prefix = 'cd ' + shlex.quote(folder) + ' && '
        scripts = data.get('scripts') or {}
        lock = posixpath.join(posixpath.dirname(manifest), 'package-lock.json')
        commands[Check.DEPENDENCY_INSTALL].append(shell_prefix + ('npm ci --no-audit --no-fund' if lock in relative else 'npm install --no-audit --no-fund'))
        for check, names in [(Check.TYPE_CHECK, ['typecheck', 'type-check']),
                             (Check.LINT, ['lint']), (Check.PRODUCTION_BUILD, ['build']),
                             (Check.UNIT_INTEGRATION_TESTS, ['test:ci', 'test']),
                             (Check.HEALTH_CHECK, ['healthcheck', 'test:smoke'])]:
            name = next((name for name in names if name in scripts), None)
            if name:
                commands[check].append(shell_prefix + 'CI=true npm run ' + shlex.quote(name))
    for requirement in sorted(path for path in relative if path.endswith('requirements.txt') and path.count('/') <= 1):
        dev = requirement.replace('requirements.txt', 'requirements-dev.txt')
        commands[Check.DEPENDENCY_INSTALL].append('python -m pip install -r ' + shlex.quote(dev if dev in relative else requirement))
    if any(path.endswith('.py') for path in relative):
        commands[Check.TYPE_CHECK].append('python -m compileall -q .')
        if any(path.startswith(('tests/', 'backend/tests/')) for path in relative):
            commands[Check.UNIT_INTEGRATION_TESTS].append('python -m pytest -q')
    return {check: ' && '.join('(' + cmd + ')' for cmd in values)
            for check, values in commands.items() if values}
