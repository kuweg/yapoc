// Portable, offline validation of the installer payload and host isolation.
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, symlink } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { composeConfig, stageSource, includeInImage, parseExtras } from './index.mjs';

for (const workspace of ['/home/alice/Work space', 'C:\\Users\\Alice\\YAPOC projects', '/Users/alice/$work']) {
  const config = composeConfig(workspace, '/source', 8050, 1000, 1000);
  assert.equal(config.services.yapoc.ports[0].host_ip, '127.0.0.1');
  assert.equal(config.services.yapoc.volumes.length, 1);
  assert.equal(config.services.yapoc.volumes[0].source.replaceAll('$$', '$'), workspace);
  if (workspace.includes('$')) assert.ok(config.services.yapoc.volumes[0].source.includes('$$'));
  assert.equal(config.services.yapoc.volumes[0].target, '/workspace');
  assert.equal(config.services.redis.ports, undefined);
  assert.equal(config.services.yapoc.privileged, undefined);
  assert.deepEqual(config.services.yapoc.cap_drop, ['ALL']);
  assert.equal(config.services.yapoc.environment.MANAGED_RESTART, 'true');
}
for (const file of ['.env', 'data/yapoc.db', 'app/memory/agents/master/MEMORY.MD', 'app/agents/master/STATUS.json',
  'app/agents/shared/KNOWLEDGE.MD', 'app/frontend/node_modules/secret.py', '.git/config']) {
  assert.equal(includeInImage(file), false, file);
}
const source = await mkdtemp(path.join(tmpdir(), 'yapoc-stage-input-'));
const destination = await mkdtemp(path.join(tmpdir(), 'yapoc-stage-output-'));
for (const file of ['docker/Dockerfile', 'docker/entrypoint.py', 'app/cli/guided_setup.py', 'app/agents/master/PROMPT.MD', '.env']) {
  await mkdir(path.dirname(path.join(source, file)), { recursive: true });
  await writeFile(path.join(source, file), file === '.env' ? 'PRIVATE_KEY=must-not-be-copied' : 'public fixture');
}
await stageSource(source, destination);
await assert.rejects(readFile(path.join(destination, '.env')));
assert.equal(await readFile(path.join(destination, 'app/agents/master/PROMPT.MD'), 'utf8'), 'public fixture');
let executable = fileURLToPath(new URL('./index.mjs', import.meta.url));
if (process.platform !== 'win32') {
  const shim = path.join(destination, 'yapoc-install');
  await symlink(executable, shim);
  executable = shim;
}
const help = spawnSync(process.execPath, [executable, '--help'], { encoding: 'utf8' });
assert.equal(help.status, 0, help.stderr);
assert.match(help.stdout, /Usage: yapoc-install/, 'npm-style bin must invoke main, not exit silently');
console.log('PASS: portable paths, localhost-only service, isolated workspace, credentials/runtime excluded from image');

const rootInstaller = fileURLToPath(new URL('../install.mjs', import.meta.url));
const rootHelp = spawnSync(process.execPath, [rootInstaller, '--help'], { cwd: tmpdir(), encoding: 'utf8' });
assert.equal(rootHelp.status, 0, rootHelp.stderr);
assert.match(rootHelp.stdout, /Usage: yapoc-install/);
const invalid = spawnSync(process.execPath, [rootInstaller, '--unknown'], { encoding: 'utf8' });
assert.equal(invalid.status, 1);
assert.match(invalid.stderr, /Unknown or incomplete option/);

assert.deepEqual(parseExtras(), []);
assert.deepEqual(parseExtras('none'), []);
assert.deepEqual(parseExtras('all'), ['embeddings', 'notebooks', 'voice']);
assert.deepEqual(parseExtras('voice,voice'), ['voice']);
assert.throws(() => parseExtras('voice;echo nope'));
for (const workspace of ['/home/alice/YAPOC', 'C:\\Users\\Alice\\YAPOC', '/Users/alice/YAPOC']) {
  assert.equal(composeConfig(workspace, '/source', 8000).services.yapoc.build.args.YAPOC_EXTRAS, '');
  assert.equal(composeConfig(workspace, '/source', 8000, null, null, ['voice', 'notebooks']).services.yapoc.build.args.YAPOC_EXTRAS, 'voice notebooks');
}
console.log('PASS: lightweight defaults and validated optional capabilities on portable paths');
