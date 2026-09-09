# Run YAPOC with Docker

Requires Docker Engine with Compose, or Docker Desktop using Linux containers.
Run these commands from the repository root. No host Python, Node, Poetry, or
Redis installation is needed.

```sh
docker compose build
docker compose run --rm --no-deps yapoc setup
docker compose up -d --wait
```

The interactive setup asks for the provider, API key, model, and optional
Telegram pairing. Open http://localhost:8000 after startup. The browser asks for
the `BACKEND_API_TOKEN` saved in `/workspace/.env`. Read that file privately with
`docker compose exec yapoc cat /workspace/.env` (it also contains provider keys;
do not share its output).

The image includes the backend and compiled dashboard; Redis runs separately
and is not exposed on the host. YAPOC runs as an unprivileged user and publishes
port 8000 on loopback. To change the host port, set `YAPOC_PORT` in your shell or
the checkout's `.env` before running Compose.

Credentials, agent edits, generated projects, and application data live in the
`yapoc-workspace` named volume. Redis uses the `redis-data` volume. The checkout's
`.env` is not copied into the image or used as backend configuration. Setup
writes a separate `.env` inside the workspace volume. The build context excludes
local credentials, databases, agent memory, and generated files.

```sh
docker compose logs -f --tail 100
docker compose stop
docker compose start
docker compose down
```

`down` preserves both volumes. `down -v` deletes the installation and Redis data.
To reconfigure, stop YAPOC before running setup so two Telegram pollers cannot
compete:

```sh
docker compose stop yapoc
docker compose run --rm --no-deps yapoc setup
docker compose up -d --wait
```

The image seeds application code into the workspace once. Rebuilding the image
does not overwrite an existing workspace's code or custom agents. Back up the
workspace before upgrades; use a separate Compose project (`docker compose -p
yapoc-new ...`) and a different `YAPOC_PORT` to test a fresh installation.
Container restart uses the built-in supervisor, including agent-requested
backend restarts. Docker restarts the containers after reboot unless stopped.

## Docker without Compose

```sh
docker build -f docker/Dockerfile -t yapoc:local .
docker network create yapoc-net
docker volume create yapoc-workspace
docker volume create yapoc-redis
docker run -d --name redis --network yapoc-net --restart unless-stopped -v yapoc-redis:/data redis:7.4-alpine redis-server --appendonly yes
docker run --rm -it -v yapoc-workspace:/workspace yapoc:local setup
docker run -d --name yapoc --network yapoc-net --init --restart unless-stopped --stop-timeout 25 --security-opt no-new-privileges:true --cap-drop ALL -p 127.0.0.1:8000:8000 -v yapoc-workspace:/workspace -e MANAGED_RESTART=true -e REDIS_URL=redis://redis:6379 -e HF_HOME=/workspace/.cache/huggingface yapoc:local
```

For local model servers, `localhost` inside the container means the container.
Configure an address reachable from Docker in the workspace `.env`; Docker
Desktop provides `host.docker.internal` for services on the host.
