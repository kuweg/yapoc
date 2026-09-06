// Portable, offline validation of the installer payload and host isolation.
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { composeConfig, stageSource, includeInImage } from './index.mjs';

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
console.log('PASS: portable paths, localhost-only service, isolated workspace, credentials/runtime excluded from image');
