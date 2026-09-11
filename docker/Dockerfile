FROM node:22-bookworm-slim AS frontend
WORKDIR /build
RUN corepack enable
COPY app/frontend/package.json app/frontend/pnpm-lock.yaml ./
RUN corepack prepare pnpm@10.13.1 --activate && pnpm install --frozen-lockfile
COPY app/frontend/ ./
RUN pnpm run build

FROM python:3.12-slim-bookworm
ARG YAPOC_EXTRAS=""
RUN apt-get update && apt-get install -y --no-install-recommends curl git libmagic1 bubblewrap util-linux build-essential \
    && rm -rf /var/lib/apt/lists/*
# Only the offline speech extra needs a Linux speech engine. This image is
# used on Linux, macOS and Windows hosts; host audio packages are not required.
RUN case " $YAPOC_EXTRAS " in *" voice "*) apt-get update && apt-get install -y --no-install-recommends espeak-ng && rm -rf /var/lib/apt/lists/* ;; esac
# Keep Poetry as the dependency/build authority. No Python setup on the host.
ENV POETRY_HOME=/opt/poetry POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp/yapoc-home
RUN curl -fsSL https://install.python-poetry.org -o /tmp/install-poetry.py \
    && python /tmp/install-poetry.py --version 2.4.2 && rm /tmp/install-poetry.py
ENV PATH="/opt/poetry/bin:${PATH}"
# Keep the JavaScript runtime in the backend image so agents can rebuild the UI.
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/lib/node_modules/ /usr/local/lib/node_modules/
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -sf ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && ln -sf ../lib/node_modules/corepack/dist/pnpm.js /usr/local/bin/pnpm \
    && ln -sf ../lib/node_modules/corepack/dist/yarn.js /usr/local/bin/yarn
WORKDIR /opt/yapoc
COPY pyproject.toml poetry.lock ./
RUN if [ -n "$YAPOC_EXTRAS" ]; then \
      poetry install --only main --no-root --no-interaction --extras "$YAPOC_EXTRAS"; \
    else poetry install --only main --no-root --no-interaction; fi
COPY app/ ./app/
COPY --from=frontend /build/dist ./app/frontend/dist
COPY docker/entrypoint.py ./entrypoint.py
RUN chmod -R a+rX /opt/yapoc
RUN groupadd --gid 10001 yapoc && useradd --uid 10001 --gid yapoc --no-create-home yapoc \
    && mkdir -p /workspace && chown yapoc:yapoc /workspace
WORKDIR /workspace
USER yapoc
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).read()"
ENTRYPOINT ["python", "/opt/yapoc/entrypoint.py"]
CMD ["serve"]
