# YAPOC guided installer

Interactive setup for Linux, Windows and macOS using Node.js 22+ and Docker.
Docker Desktop must use Linux containers; Linux can also use Docker Engine with
the Compose plugin. Python, Poetry, Node build tools and Redis run in containers.

From a source checkout:

```sh
node installer/index.mjs --source .
```

The installer asks for a master folder, an AI provider/key/model, and optional
Telegram pairing. It starts YAPOC, checks the dashboard and opens a browser.
Re-running the command resumes installation or offers to keep existing settings.

Options: `--source PATH`, `--ref BRANCH_OR_COMMIT`, `--workspace PATH`,
`--extras embeddings,notebooks,voice` (also `all` or `none`), `--no-browser`, `--help`. API keys are never accepted as command-line arguments.

See `docs/installation.md` in the source repository for prerequisites,
platform-specific launch commands, troubleshooting and validation status.

This package is prepared for npm distribution. Until it is published to npm,
use the source checkout or the GitHub package command in the installation guide;
do not assume `npx yapoc-installer` is available from the registry.

The default is the lightweight core. Optional packages are installed in the
container, without changing the folder → provider/key → optional Telegram flow.
Re-runs keep the existing extras unless `--extras` is supplied.
