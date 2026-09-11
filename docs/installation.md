# Guided installation

To run directly with Docker Compose (without the Node launcher), follow the
[Docker instructions](../docker/README.md). The root `compose.yaml` builds the
dashboard and backend and starts a separate Redis container.

The guided installer supports **Linux, Windows and macOS through a Linux Docker
runtime**. It asks for a master folder, a provider/key/model, optional Telegram
pairing, then starts YAPOC and opens the dashboard. No Python, Poetry, Redis or
frontend build setup is required on the host.

## Prerequisites

- Node.js **22 or newer**, including npm: <https://nodejs.org/en/download>.
- Docker Desktop, running with Linux containers, on Windows/macOS. Linux can use
  Docker Desktop or Docker Engine with the Compose plugin. Installation help:
  <https://docs.docker.com/get-started/get-docker/>.
- `tar` for a downloaded source archive. Linux/macOS normally include it; current
  Windows includes `tar.exe`. A local `--source` checkout skips archive extraction.
- Internet access for the initial image build and the chosen AI provider.

The installer checks Docker and offers a retry after you install/start it. It
does not silently grant Docker privileges or install host services. Windows
users should complete Docker Desktop's WSL/virtualization setup when prompted.
The default build excludes the local embedding/ML stack. Opting into the
`embeddings` extra can add large downloads. Subsequent runs reuse build caches.

## Launch

These commands target the `feat/guided-installer` preview branch. After it is
merged, `main` can be used instead. The launcher resolves the selected source
reference to a commit before downloading it.

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/kuweg/yapoc/feat/guided-installer/scripts/install-guided.sh | YAPOC_REF=feat/guided-installer bash
```

### Windows PowerShell

```powershell
$env:YAPOC_REF = 'feat/guided-installer'
Invoke-RestMethod https://raw.githubusercontent.com/kuweg/yapoc/feat/guided-installer/scripts/install-guided.ps1 | Invoke-Expression
```

### npm / npx, on any platform

The npm registry package has **not** been published. With Git installed, run the
package directly from the branch:

```sh
npx --yes --package=github:kuweg/yapoc#feat/guided-installer yapoc-install --ref feat/guided-installer
```

From a source checkout, no npm dependencies are needed:

```sh
node install.mjs
```

Root launchers also support `bash install.sh` (Linux/macOS) and
`.\install.ps1` (Windows PowerShell). All accept the options listed below and
locate this checkout independently of the working directory. Use
`node install.mjs --help` to check the launcher without starting installation.

The supported cross-platform runtime is Docker with Linux containers. File
locking works on Unix and Windows, but agent shell execution and process
management still require Unix APIs; native Windows backend execution is not
supported. Linux-only systemd scripts are optional and are not used by the
guided installer.

## The five steps

1. **Master folder.** Default: `~/YAPOC` (your user profile's `YAPOC` directory on
   Windows). Choose a dedicated folder. YAPOC may create, modify and delete files
   there without per-action user prompts, subject to its built-in tool rules.
   It also stores its application under `app/`, state under `data/`, and
   credentials in `.env` there. Existing reserved paths are rejected on a fresh
   install; unrelated projects can coexist. Never select an entire home or drive.
2. **Allowed provider.** Select a cloud provider, paste its hidden API key, and
   choose a model. Invalid credentials offer retry/cancel. A custom model ID can
   be entered. Key validation does not guarantee that every model supports tools
   or that the account has generation quota. Fresh agents use only the selected
   provider; developer fallback chains are removed.
3. **Telegram, optional.** Create a dedicated bot with `@BotFather`, enter its
   token, open the displayed private-chat link and press **Start**. The unique
   pairing code binds notifications to your private chat; no manual chat-ID
   lookup is needed. An existing webhook is left untouched and setup requests
   a dedicated bot. Failed pairing can be retried or skipped. The existing bot
   integration also permits your paired chat to interact with YAPOC.
4. **Configure and run.** Settings are saved, Redis and the backend start, and
   the installer checks authenticated access and the built dashboard. The server
   is published on loopback only, using an available port from 8000–8099. Redis
   is not published to the host.
5. **Open browser.** The dashboard opens with automatic local authentication.
   The access token is transferred in a URL fragment, immediately removed by the
   UI, and exchanged for the normal HTTP-only authentication cookie. It is not
   put in HTTP URLs or printed by the installer. If opening fails, setup prints
   the dashboard URL and explains where to find the access token.

Only the master folder is mounted into YAPOC. Docker's socket, your whole home,
and host system directories are not mounted. Agents can use the container's
tools and filesystem; this is not permission to administer the host OS. Docker
is the execution boundary, rather than a claim that shell commands are safely
restricted merely by their working directory.

## Resume, start, stop and logs

Re-run the same install command and choose the same folder. Existing settings
can be kept or reconfigured. A cancelled reconfiguration restarts a previously
running installation with its existing configuration when cancellation occurs
before configuration is saved. Backups of `.env` are written before replacement.

Host control files are stored outside the agent-writable folder at
`~/.yapoc/installations/<folder-hash>/`. This prevents an agent from editing the
Compose definition to add host mounts on the next launch. The installer prints
the exact commands for your instance:

```sh
docker compose -f "<printed-compose-path>" stop
docker compose -f "<printed-compose-path>" start
docker compose -f "<printed-compose-path>" logs --tail 100
```

Docker must be running after login/reboot. Services use `restart: unless-stopped`.
Inside the container, one supervisor owns backend restarts. `server_restart`
saves the continuation and requests shutdown; the supervisor launches the next
backend, avoiding competing replacement processes.

Setup does **not** overwrite a completed installation's application code. Custom
agents and self-modifications survive re-runs and container recreation. Automatic
code updates/rollback are not part of this first installer; use a new dedicated
folder to evaluate a newer source version while retaining the old installation.
Do not delete the old folder or Docker Redis volume until data has been backed up.

## Options

| Option | Meaning |
| --- | --- |
| `--workspace PATH` | Prefill the master folder; other setup remains interactive |
| `--source PATH` | Build from a local checkout instead of downloading source |
| `--ref REF` | Source branch, tag or commit for a fresh installation |
| `--no-browser` | Print the URL without launching a browser |
| `--help` | Display usage without making changes |

No API-key flags or noninteractive credential shortcuts are provided. npm only
distributes the launcher; it does not run YAPOC through an npm install hook.

## Troubleshooting and validation

- **Docker permission denied:** fix access to your Docker Engine or start Docker
  Desktop, then retry. Setup will not continue while Docker is unavailable.
- **Folder sharing denied:** permit that folder in Docker Desktop and retry.
- **Source lacks installer files:** use this branch or a checkout containing
  `docker/Dockerfile` and `app/cli/guided_setup.py`.
- **Build fails:** inspect the failed dependency step, restore connectivity/free
  disk space, and retry. A failed build is never reported as a successful install.
- **Startup times out:** inspect the printed logs command. Existing data is
  preserved. No browser is opened until authenticated access and HTML succeed.
- **Bot is already polling elsewhere:** stop that bot process or create a
  dedicated bot. Setup does not remove another application's webhook.
- **API key valid but chat fails:** verify the chosen model ID, tool support and
  account quota. Setup validates credentials without charging for a completion.

Local checks cover launcher packaging, Windows/macOS/Linux path forms, Compose
configuration, clean image staging, backend/configuration behavior, frontend
build and browser authentication. Six isolated Python checks passed, including
the guided configuration flow, credential-file preservation, Telegram pairing
correlation, and restart handoff. Playwright verified that installer browser
authentication opens chat, clears the fragment, and survives reload. Provider
and Telegram calls in those checks used fixtures, not live credentials.
The GitHub workflow runs host checks on all
three OSes and builds the real container on Linux. A complete local Docker run
could not be performed in the development session because Docker socket access
was denied and sudo required a password. Live provider and Telegram pairing
require the installer's own credentials and are not exercised using someone
else's account during validation.

## Lightweight core and optional capabilities

The default installation keeps the three interactive choices in this order:

1. Choose the YAPOC working folder.
2. Choose the initial provider and enter its API key in a masked prompt; select a model.
3. Optionally connect a Telegram bot, or skip it. An empty bot token also offers Skip.

No API key is accepted as a command-line argument. The installer then saves the
configuration, starts the services and opens the dashboard as before.

The core includes the dashboard, providers, Telegram integration, GitHub, document
handling, and keyword memory search. It does **not** install the local ML stack,
notebook kernel, or offline speech engine. Optional capabilities use standard
[Python extras](https://packaging.python.org/en/latest/specifications/pyproject-toml/#dependencies-optional-dependencies):

| Extra | Adds | Without it |
| --- | --- | --- |
| `embeddings` | sentence-transformers and its ML dependencies | Memory remains indexed and searchable by keyword; no model downloads |
| `notebooks` | ipykernel | Ordinary agent Python execution still works; no notebook kernel |
| `voice` | pyttsx3 | Text and configured cloud speech remain available; offline speech reports setup guidance |

Choose extras explicitly when launching setup; the three interactive choices
stay the same:

```sh
node install.mjs --extras embeddings,voice
node install.mjs --extras all
```

Shell launchers forward the same flags:

```bash
bash install.sh --extras notebooks
```

```powershell
.\install.ps1 --extras notebooks
```

A re-run without `--extras` keeps the installation's previous selection. Passing
`--extras none` selects the core image. Changing the selection rebuilds the
runtime without deleting the workspace or credentials. Use the same installer
source version when modifying an existing installation; setup is not an app
source-code upgrade.

For direct Compose, set the build variable before building:

```bash
YAPOC_EXTRAS="embeddings voice" docker compose build yapoc
docker compose up -d
```

```powershell
$env:YAPOC_EXTRAS = 'embeddings voice'
docker compose build yapoc
docker compose up -d
```

For a native Linux development checkout:

```sh
poetry install --only main                 # core runtime
poetry install -E embeddings -E voice      # selected capabilities, plus dev group
poetry install --all-extras                # all optional capabilities
poetry run yapoc restart
poetry run yapoc memory-embeddings          # optional: embed existing keyword-only memory
```

Repeat the desired extras on subsequent Poetry installs; omitted extras may be
removed by Poetry. The lockfile includes all optional dependencies for reproducible
resolution, but a core installation does not install them. Existing keyword-only
rows stay usable; `memory-embeddings` fills their vectors in batches without
recreating memory or changing existing vectors. The embeddings model downloads
on first semantic use or explicit backfill, never in the core-only path.

### OS behavior

The Node launcher and PowerShell/Bash entrypoints use the same installer and
folder/provider/Telegram flow. Windows and macOS run the backend in Linux
containers through [Docker Desktop](https://docs.docker.com/desktop/); Linux may
also use Docker Engine with Compose. No Linux package-manager commands run on the
Windows/macOS host, and the image does not force an x86 architecture.

The `voice` image installs Linux eSpeak only when requested. Native Linux offline
speech also needs an OS speech engine (`espeak-ng` on Debian/Ubuntu, or the
corresponding package for the distribution). Installing the Python voice extra
alone does not configure microphone access or host audio forwarding. Notebook
support adds a kernel, not a notebook web interface. Native Windows/macOS backend
execution is not the supported path for agent shell isolation; use Docker.

Validation includes portable installer checks on Linux/Windows/macOS in CI, core
and embedding-enabled backend test jobs, and a core container import/build check.
A Linux-only development test does not establish a Windows/macOS end-to-end pass.
