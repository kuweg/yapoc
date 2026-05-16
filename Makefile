.PHONY: start stop start-ui start-backend start-redis stop-ui stop-backend stop-redis

FRONTEND_DIR = app/frontend
REDIS_PIDFILE = /tmp/yapoc-redis.pid

# ── Combined ──────────────────────────────────────────────────────────
start: start-redis start-backend start-ui

stop: stop-ui stop-backend stop-redis

# ── Individual starts ─────────────────────────────────────────────────
start-redis:
	@if redis-cli ping > /dev/null 2>&1; then \
		echo "Redis already running"; \
	else \
		redis-server --daemonize yes --pidfile $(REDIS_PIDFILE); \
		echo "Redis started"; \
	fi

start-backend:
	@poetry run yapoc start &
	@echo "Backend starting on http://localhost:8000"

start-ui:
	@cd $(FRONTEND_DIR) && pnpm dev &
	@echo "UI starting on http://localhost:5173"

# ── Individual stops ──────────────────────────────────────────────────
stop-redis:
	@if [ -f $(REDIS_PIDFILE) ]; then \
		kill $$(cat $(REDIS_PIDFILE)) 2>/dev/null && rm -f $(REDIS_PIDFILE) && echo "Redis stopped" || echo "Redis already stopped"; \
	elif redis-cli ping > /dev/null 2>&1; then \
		redis-cli shutdown && echo "Redis stopped"; \
	else \
		echo "Redis not running"; \
	fi

stop-backend:
	@lsof -ti:8000 -sTCP:LISTEN | xargs kill 2>/dev/null && echo "Backend stopped" || echo "Backend not running"

stop-ui:
	@lsof -ti:5173 -sTCP:LISTEN | xargs kill 2>/dev/null && echo "UI stopped" || echo "UI not running"
