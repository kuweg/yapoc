#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, readdir, copyFile, mkdtemp, realpath, lstat, access } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline/promises';
import net from 'node:net';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const exists = async file => { try { await access(file); return true; } catch { return false; } };
const literal = value => value.replaceAll('$', '$$'); // Compose interpolation is independent of JSON quoting.

export function composeConfig(workspace, context, port, uid = null, gid = null) {
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
        build: { context: literal(context), dockerfile: 'docker/Dockerfile' },
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
  while (true) {
    try {
      await run('docker', ['compose', 'version'], { capture: true });
      const os = await run('docker', ['info', '--format', '{{.OSType}}'], { capture: true });
      if (os !== 'linux') throw new Error('Switch Docker Desktop to Linux containers.');
      const endpoint = await run('docker', ['context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'], { capture: true });
      if (!/^(unix:|npipe:)/.test(endpoint) || process.env.DOCKER_HOST?.match(/^(tcp|ssh):/)) {
        throw new Error('Select a local Docker context so your chosen folder is mounted on this computer.');
      }
      return;
    } catch (error) {
      console.log(`Docker is not ready: ${error.message}\nInstall/start Docker Desktop (or Docker Engine + Compose on Linux):\nhttps://docs.docker.com/get-started/get-docker/`);
      const answer = await question('Press Enter to retry, or type cancel');
      if (answer.toLowerCase() === 'cancel') throw new Error('Installation cancelled; existing files were preserved.');
    }
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

async function downloadSource() {
  console.log('Downloading YAPOC source…');
  const result = await fetch('https://api.github.com/repos/kuweg/yapoc/commits/main', { signal: AbortSignal.timeout(30000) });
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
  if (args.includes('--help')) {
    console.log('YAPOC guided installer (Node 22+, Docker)\nUsage: yapoc-install [--source PATH] [--workspace PATH] [--no-browser]\nLinux, Windows and macOS. Credentials are requested interactively.');
    return;
  }
  let source, requestedWorkspace, noBrowser = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--no-browser') noBrowser = true;
    else if (['--source', '--workspace'].includes(args[i]) && args[i+1]) {
      const option = args[i++];
      if (option === '--source') source = path.resolve(args[i]); else requestedWorkspace = args[i];
    } else throw new Error(`Unknown or incomplete option: ${args[i]}`);
  }
  if (!process.stdin.isTTY) throw new Error('Run the installer in an interactive terminal. It never accepts API keys on the command line.');
  console.log('\nYAPOC guided installation\n1/5 — Choose the master folder\nYAPOC can create, modify and delete files inside this folder. Its app and data also live here.\nOnly this folder is shared with its container; the Docker socket is never mounted.');
  let workspace = requestedWorkspace || await question('Master folder', path.join(homedir(), 'YAPOC'));
  if (workspace.startsWith('~/') || workspace.startsWith('~\\')) workspace = path.join(homedir(), workspace.slice(2));
  workspace = path.resolve(workspace);
  if (workspace === path.parse(workspace).root || workspace === homedir()) throw new Error('Choose a dedicated folder inside your home, not the entire home or drive.');
  await mkdir(workspace, { recursive: true });
  workspace = await realpath(workspace);
  const marker = path.join(workspace, '.yapoc-install.json');
  if (!await exists(marker)) {
    for (const reserved of ['app', 'data', '.env', 'pyproject.toml', 'poetry.lock']) {
      if (await exists(path.join(workspace, reserved))) throw new Error(`The folder already contains ${reserved}. Choose a different folder; existing files were not overwritten.`);
    }
  }
  console.log(`Workspace: ${workspace}`);
  await ensureDocker();
  const control = path.join(workspace, '.yapoc-installer');
  await mkdir(control, { recursive: true });
  const composeFile = path.join(control, 'compose.json');
  let config;
  if (await exists(composeFile)) {
    config = JSON.parse(await readFile(composeFile, 'utf8'));
  } else {
    const context = path.join(control, 'image-source');
    await mkdir(context, { recursive: true });
    const local = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    source ||= await exists(path.join(local, 'pyproject.toml')) ? local : await downloadSource();
    await stageSource(source, context);
    const port = await availablePort();
    config = composeConfig(workspace, context, port, process.getuid?.() ?? null, process.getgid?.() ?? null);
    await writeFile(composeFile, JSON.stringify(config, null, 2) + '\n');
  }
  const docker = (...args) => run('docker', ['compose', '-f', composeFile, ...args]);
  const prefix = `docker compose -f "${composeFile}"`;
  console.log(`\nManage this installation:\n  ${prefix} stop\n  ${prefix} start\n  ${prefix} logs --tail 100\n`);
  console.log('Preparing the runtime and built dashboard. First installation downloads dependencies; retries reuse the build cache.');
  await docker('build', 'yapoc');
  // No live bot poller may compete with pairing/reconfiguration.
  await docker('stop', 'yapoc');
  await docker('run', '--rm', '--no-deps', 'yapoc', 'setup');
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

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(error => { console.error(`\nSetup stopped: ${error.message}\nRe-run the same command to continue. Existing settings and projects are preserved.`); process.exitCode = 1; });
}
