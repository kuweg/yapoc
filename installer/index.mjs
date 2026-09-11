#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, readdir, copyFile, mkdtemp, realpath, access } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline/promises';
import net from 'node:net';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const exists = async file => { try { await access(file); return true; } catch { return false; } };
const literal = value => value.replaceAll('$', () => '$$'); // Avoid JS replacement-string escaping too.

export function hostInfo(platform = process.platform, arch = process.arch) {
  const names = { darwin: 'macOS', linux: 'Linux', win32: 'Windows' };
  if (!names[platform]) throw new Error(`Unsupported operating system: ${platform}`);
  return { platform, name: names[platform], arch,
    dockerHelp: platform === 'darwin'
      ? 'Open Docker Desktop from Applications. If missing, install Docker Desktop for Mac (Apple silicon for arm64, Intel for x64): https://docs.docker.com/desktop/setup/install/mac-install/'
      : platform === 'win32'
        ? 'Start Docker Desktop with Linux containers and WSL 2: https://docs.docker.com/desktop/setup/install/windows-install/'
        : 'Start Docker Engine and install the Compose plugin, or start Docker Desktop: https://docs.docker.com/engine/install/' };
}

export function resolveHostPath(value, { platform = process.platform, home = homedir(), cwd = process.cwd() } = {}) {
  const paths = platform === 'win32' ? path.win32 : path.posix;
  let input = value.trim();
  if ((input.startsWith('"') && input.endsWith('"')) || (input.startsWith("'") && input.endsWith("'"))) input = input.slice(1, -1);
  if (!input || /[\x00-\x1f]/.test(input)) throw new Error('Enter a valid folder path.');
  if (platform !== 'win32' && (/^[A-Za-z]:/.test(input) || input.includes('\\'))) {
    throw new Error(`This is a ${hostInfo(platform).name} installation. Use a local folder such as ${paths.join(home, 'YAPOC')}, not a Windows path. Spaces can be entered directly without backslashes.`);
  }
  if (input === '~') input = home;
  else if (input.startsWith('~/') || (platform === 'win32' && input.startsWith('~\\'))) input = paths.join(home, input.slice(2));
  else if (input.startsWith('~')) throw new Error('Use ~/ for your home folder, or enter an absolute path.');
  return paths.resolve(cwd, input);
}

export async function checkPrerequisites(execute = run, platform = process.platform) {
  const host = hostInfo(platform);
  try { await execute('docker', ['compose', 'version'], { capture: true }); }
  catch { return { ready: false, detail: 'Docker CLI or Compose is unavailable.', help: host.dockerHelp }; }
  try {
    const os = await execute('docker', ['info', '--format', '{{.OSType}}'], { capture: true });
    if (os !== 'linux') return { ready: false, detail: 'YAPOC needs a Linux container runtime.', help: host.dockerHelp };
    const endpoint = await execute('docker', ['context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'], { capture: true });
    if (!/^(unix:|npipe:)/.test(endpoint) || process.env.DOCKER_HOST?.match(/^(tcp|ssh):/)) {
      return { ready: false, detail: 'The selected Docker context is remote.', help: 'Select a local Docker context so the chosen folder is on this computer.' };
    }
    return { ready: true, detail: 'Docker and Compose are ready.' };
  } catch { return { ready: false, detail: 'Docker is installed but its engine is not reachable.', help: host.dockerHelp }; }
}

export function parseExtras(value = '') {
  const allowed = ['embeddings', 'notebooks', 'voice'];
  if (value === 'all') return allowed;
  if (!value || value === 'none') return [];
  const selected = [...new Set(value.split(',').map(name => name.trim()))];
  if (selected.some(name => !allowed.includes(name))) throw new Error('Extras must be embeddings, notebooks, voice, all, or none.');
  return selected;
}

export function composeConfig(workspace, context, port, uid = null, gid = null, extras = []) {
  return {
    name: 'yapoc-' + createHash('sha256').update(workspace).digest('hex').slice(0, 10),
    services: {
      redis: {
        image: 'redis:7.4-alpine', restart: 'unless-stopped',
        command: ['redis-server', '--appendonly', 'yes'],
        volumes: ['redis-data:/data'],
        healthcheck: { test: ['CMD', 'redis-cli', 'ping'], interval: '3s', timeout: '2s', retries: 20 },
      },
      yapoc: {
        build: { context: literal(context), dockerfile: 'docker/Dockerfile', args: { YAPOC_EXTRAS: parseExtras(extras.join(',')).join(' ') } },
        init: true, restart: 'unless-stopped', stop_grace_period: '25s',
        ...(uid === null ? {} : { user: `${uid}:${gid}` }),
        security_opt: ['no-new-privileges:true'], cap_drop: ['ALL'],
        ports: [{ target: 8000, published: String(port), host_ip: '127.0.0.1' }],
        volumes: [{ type: 'bind', source: literal(workspace), target: '/workspace' }],
        environment: { MANAGED_RESTART: 'true', HF_HOME: '/workspace/.cache/huggingface' },
        depends_on: { redis: { condition: 'service_healthy' } },
      },
    },
    volumes: { 'redis-data': {} },
  };
}

export async function run(command, args, { capture = false, ...options } = {}) {
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit', shell: false, ...options });
    let output = '';
    if (capture) {
      child.stdout.on('data', data => { output += data; });
      child.stderr.on('data', data => { output += data; });
    }
    child.on('error', reject);
    child.on('exit', code => code === 0 ? resolve(output.trim()) : reject(new Error(`${command} exited with ${code}${capture ? ': ' + output.trim() : ''}`)));
  });
}

async function question(message, fallback = '') {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  try { return (await rl.question(`${message}${fallback ? ` [${fallback}]` : ''}: `)).trim() || fallback; }
  finally { rl.close(); }
}

async function openBrowser(url) {
  // Arguments never pass through a shell. In particular, spaces and & in URLs
  // or selected folders must not become shell syntax on Windows.
  const [cmd, args] = process.platform === 'win32'
    ? ['rundll32.exe', ['url.dll,FileProtocolHandler', url]]
    : process.platform === 'darwin' ? ['open', [url]] : ['xdg-open', [url]];
  try { await run(cmd, args, { capture: true }); return true; }
  catch { return false; }
}

async function ensureDocker() {
  let offeredOpen = false;
  while (true) {
    const result = await checkPrerequisites();
    if (result.ready) { console.log(`  ✓ ${result.detail}`); return; }
    console.log(`\n  ! ${result.detail}\n${result.help}`);
    if (process.platform === 'darwin' && !offeredOpen) {
      offeredOpen = true;
      if ((await question('Open Docker Desktop now? (Y/n)', 'y')).toLowerCase() === 'y') {
        try { await run('open', ['-a', 'Docker'], { capture: true }); }
        catch { console.log('Docker Desktop could not be opened. Install it using the link above.'); }
      }
    }
    const answer = await question('When Docker is ready, press Enter to retry, or type cancel');
    if (answer.toLowerCase() === 'cancel') throw new Error('Installation cancelled; existing files were preserved.');
  }
}

export function includeInImage(relative) {
  const p = relative.replaceAll('\\', '/');
  if (['pyproject.toml', 'poetry.lock', 'docker/Dockerfile', 'docker/entrypoint.py'].includes(p)) return true;
  if (!p.startsWith('app/')) return false;
  if (/\/(node_modules|__pycache__|dist|\.vite)\//.test(p) || p.startsWith('app/memory/') || p.startsWith('app/projects/')) return false;
  if (p.startsWith('app/frontend/')) {
    return p.startsWith('app/frontend/src/') || p.startsWith('app/frontend/public/') ||
      /^app\/frontend\/(package\.json|pnpm-lock\.yaml|index\.html|vite\.config\.ts|tsconfig[^/]*\.json)$/.test(p);
  }
  return p.endsWith('.py') || /^app\/agents\/[^/]+\/(PROMPT\.MD|CONFIG\.yaml)$/.test(p) ||
    p === 'app/config/agent-settings.json' || /^app\/skills\/[^/]+\.yaml$/.test(p);
}

export async function stageSource(source, destination) {
  async function walk(relative = '') {
    for (const entry of await readdir(path.join(source, relative), { withFileTypes: true })) {
      const name = path.join(relative, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) {
        if (['.git', '.env', 'node_modules', '__pycache__', 'data', 'dist', '.venv', 'memory', 'projects'].includes(entry.name)) continue;
        if (!relative && !['app', 'docker'].includes(entry.name)) continue;
        await walk(name);
      } else if (includeInImage(name)) {
        await mkdir(path.dirname(path.join(destination, name)), { recursive: true });
        await copyFile(path.join(source, name), path.join(destination, name));
      }
    }
  }
  await walk();
  for (const required of ['docker/Dockerfile', 'docker/entrypoint.py', 'app/cli/guided_setup.py']) {
    if (!await exists(path.join(destination, required))) throw new Error('This source version does not contain the guided installer. Use the current checkout with --source.');
  }
}

async function downloadSource(ref) {
  console.log('Downloading YAPOC source…');
  const result = await fetch(`https://api.github.com/repos/kuweg/yapoc/commits/${encodeURIComponent(ref)}`, { signal: AbortSignal.timeout(30000) });
  if (!result.ok) throw new Error(`Could not resolve release source: HTTP ${result.status}`);
  const { sha } = await result.json();
  if (!/^[0-9a-f]{40}$/.test(sha)) throw new Error('Invalid source revision');
  const archive = await fetch(`https://codeload.github.com/kuweg/yapoc/tar.gz/${sha}`, { signal: AbortSignal.timeout(120000) });
  if (!archive.ok) throw new Error(`Source download failed: HTTP ${archive.status}`);
  const temporary = await mkdtemp(path.join(tmpdir(), 'yapoc-source-'));
  const file = path.join(temporary, 'source.tar.gz');
  await writeFile(file, Buffer.from(await archive.arrayBuffer()));
  const source = path.join(temporary, 'source');
  await mkdir(source);
  await run('tar', ['-xzf', file, '-C', source, '--strip-components=1']);
  console.log(`Using source revision ${sha}`);
  return source;
}

export async function availablePort(start = 8000) {
  for (let port = start; port < start + 100; port++) {
    const free = await new Promise(resolve => {
      const server = net.createServer();
      server.once('error', () => resolve(false));
      server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)));
    });
    if (free) return port;
  }
  throw new Error('No free local port found. Free a port in 8000–8099 and retry.');
}

async function waitReady(url, token, seconds = 180) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${url}/api/auth/status`, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(3000) });
      if (response.ok && (await response.json()).authenticated) {
        const ui = await fetch(url, { signal: AbortSignal.timeout(3000) });
        if (ui.ok && (await ui.text()).includes('id="root"')) return;
      }
    } catch { /* backend still starting */ }
    await sleep(1500);
  }
  throw new Error('YAPOC did not become ready in 3 minutes. Run the logs command below, then re-run setup.');
}

export async function main(args = process.argv.slice(2)) {
  if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('Install Node.js 22 or newer and retry.');
  if (args.includes('--help')) {
    console.log('YAPOC guided installer (Node 22+, Docker)\nUsage: yapoc-install [--source PATH] [--ref BRANCH_OR_COMMIT] [--workspace PATH] [--extras embeddings,notebooks,voice|all|none] [--no-browser] [--check]\nLinux, Windows and macOS. Credentials are requested interactively.');
    return;
  }
  if (args.includes('--check')) {
    const host = hostInfo();
    console.log(`YAPOC installer · ${host.name} (${host.arch}) · Node ${process.versions.node}`);
    const result = await checkPrerequisites();
    console.log(`${result.detail}${result.help ? '\n' + result.help : ''}`);
    if (!result.ready) process.exitCode = 1;
    return;
  }
  let source, requestedWorkspace, extras, ref = 'main', noBrowser = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--no-browser') noBrowser = true;
    else if (['--source', '--workspace', '--ref', '--extras'].includes(args[i]) && args[i+1]) {
      const option = args[i++];
      if (option === '--source') source = resolveHostPath(args[i]);
      else if (option === '--ref') ref = args[i];
      else if (option === '--extras') extras = parseExtras(args[i]);
      else requestedWorkspace = args[i];
    } else throw new Error(`Unknown or incomplete option: ${args[i]}`);
  }
  if (!process.stdin.isTTY) throw new Error('Run the installer in an interactive terminal. It never accepts API keys on the command line.');
  const host = hostInfo();
  console.log(`\nYAPOC setup · ${host.name} (${host.arch})\nWorking folder → runtime → provider / API key → Telegram (optional) → ready`);
  console.log('\n1/5 — Choose your working folder\nYour YAPOC app, settings and projects will live here. Agents can edit files in this folder.');
  let workspace;
  while (!workspace) {
    const input = requestedWorkspace || await question('Working folder', path.join(homedir(), 'YAPOC'));
    try { workspace = resolveHostPath(input); }
    catch (error) {
      if (requestedWorkspace) throw error;
      console.log(`  ! ${error.message}`);
    }
  }
  if (workspace === path.parse(workspace).root || workspace === homedir()) throw new Error('Choose a dedicated folder inside your home, not the entire home or drive.');
  await mkdir(workspace, { recursive: true });
  workspace = await realpath(workspace);
  if (workspace === path.parse(workspace).root || workspace === await realpath(homedir())) throw new Error('Choose a dedicated folder, not a link to your entire home or drive.');
  const marker = path.join(workspace, '.yapoc-install.json');
  if (!await exists(marker)) {
    for (const reserved of ['app', 'data', '.env', 'pyproject.toml', 'poetry.lock']) {
      if (await exists(path.join(workspace, reserved))) throw new Error(`The folder already contains ${reserved}. Choose a different folder; existing files were not overwritten.`);
    }
  }
  console.log(`Workspace: ${workspace}`);
  console.log('\nPreparing your runtime — checking Docker and Compose…');
  await ensureDocker();
  // Keep host orchestration OUTSIDE the agent-writable folder. Otherwise an
  // agent could edit Compose and gain extra host mounts on the next launch.
  const installId = createHash('sha256').update(workspace).digest('hex').slice(0, 10);
  const control = path.join(homedir(), '.yapoc', 'installations', installId);
  await mkdir(control, { recursive: true, mode: 0o700 });
  const composeFile = path.join(control, 'compose.json');
  let config;
  if (await exists(composeFile)) {
    config = JSON.parse(await readFile(composeFile, 'utf8'));
  } else {
    const context = path.join(control, 'image-source');
    await mkdir(context, { recursive: true });
    const local = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    source ||= await exists(path.join(local, 'pyproject.toml')) ? local : await downloadSource(ref);
    await stageSource(source, context);
    const port = await availablePort();
    config = composeConfig(workspace, context, port, process.platform === 'linux' ? process.getuid() : null, process.platform === 'linux' ? process.getgid() : null, extras ?? []);
    await writeFile(composeFile, JSON.stringify(config, null, 2) + '\n');
  }
  if (extras !== undefined) {
    config.services.yapoc.build.args = { ...config.services.yapoc.build.args, YAPOC_EXTRAS: extras.join(' ') };
    await writeFile(composeFile, JSON.stringify(config, null, 2) + '\n');
  }
  console.log(`Optional capabilities: ${config.services.yapoc.build.args?.YAPOC_EXTRAS || 'none (lightweight core)'}`);
  const docker = (...args) => run('docker', ['compose', '-f', composeFile, ...args]);
  const quotedCompose = process.platform === 'win32' ? `'${composeFile.replaceAll("'", "''")}'` : `'${composeFile.replaceAll("'", "'\"'\"'")}'`;
  const prefix = `docker compose -f ${quotedCompose}`;
  console.log(`\nManage this installation:\n  ${prefix} stop\n  ${prefix} start\n  ${prefix} logs --tail 100\n`);
  console.log('\nPreparing the runtime and dashboard…\nThe first build may take several minutes. Downloads and build progress appear below.');
  await docker('build', 'yapoc');
  // No live bot poller may compete with pairing/reconfiguration.
  const wasRunning = Boolean((await run('docker', ['compose', '-f', composeFile, 'ps', '--status', 'running', '-q', 'yapoc'], { capture: true })).trim());
  await docker('stop', 'yapoc');
  try {
    await docker('run', '--rm', '--no-deps', 'yapoc', 'setup');
  } catch (error) {
    if (wasRunning) await docker('up', '-d');
    throw error;
  }
  await docker('up', '-d');
  const port = config.services.yapoc.ports[0].published;
  const url = `http://localhost:${port}`;
  // This file is local to the chosen workspace. Never print its contents.
  const env = await readFile(path.join(workspace, '.env'), 'utf8');
  const token = env.match(/^BACKEND_API_TOKEN='([A-Za-z0-9_-]+)'$/m)?.[1];
  if (!token) throw new Error('Setup did not save a valid browser access token. Reconfigure and retry.');
  console.log('Waiting for the backend and dashboard…');
  await waitReady(url, token);
  console.log(`\n5/5 — YAPOC is ready at ${url}`);
  if (!noBrowser && await openBrowser(`${url}/#setup-token=${encodeURIComponent(token)}`)) {
    console.log('Opened YAPOC in your browser.');
  } else {
    console.log(`Open ${url} manually. The access token is BACKEND_API_TOKEN in your workspace's .env file.`);
  }
}

// npm launches Unix bins through a symlink under node_modules/.bin.
const invokedPath = process.argv[1] ? await realpath(process.argv[1]).catch(() => '') : '';
if (invokedPath && import.meta.url === pathToFileURL(invokedPath).href) {
  main().catch(error => { console.error(`\nSetup stopped: ${error.message}\nRe-run the same command to continue. Existing settings and projects are preserved.`); process.exitCode = 1; });
}
