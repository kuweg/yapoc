FROM node:22-bookworm-slim AS frontend
WORKDIR /build
RUN corepack enable
COPY app/frontend/package.json app/frontend/pnpm-lock.yaml ./
RUN corepack prepare pnpm@10.13.1 --activate && pnpm install --frozen-lockfile
COPY app/frontend/ ./
RUN pnpm run build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends curl git libmagic1 espeak-ng build-essential \
    && rm -rf /var/lib/apt/lists/*
# Keep Poetry as the dependency/build authority. No Python setup on the host.
ENV POETRY_HOME=/opt/poetry POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp/yapoc-home
RUN curl -fsSL https://install.python-poetry.org -o /tmp/install-poetry.py \
    && python /tmp/install-poetry.py --version 2.2.1 && rm /tmp/install-poetry.py
ENV PATH="/opt/poetry/bin:${PATH}"
WORKDIR /opt/yapoc
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction
COPY app/ ./app/
COPY --from=frontend /build/dist ./app/frontend/dist
COPY docker/entrypoint.py ./entrypoint.py
WORKDIR /workspace
ENTRYPOINT ["python", "/opt/yapoc/entrypoint.py"]
CMD ["serve"]
