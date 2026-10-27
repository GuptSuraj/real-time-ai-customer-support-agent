.PHONY: install migrate seed api agent web test types up
install:
	uv sync --frozen
	pnpm --dir apps/web install --frozen-lockfile
migrate:
	uv run alembic -c services/api/alembic.ini upgrade head
seed:
	PYTHONPATH=services/api uv run python -m support_api.seed
api:
	PYTHONPATH=services/api uv run uvicorn support_api.main:app --reload --host 127.0.0.1 --port 8000
agent:
	PYTHONPATH=services/api:services/agent uv run python -m support_agent.worker dev
web:
	pnpm --dir apps/web dev
test:
	uv run pytest -q
	pnpm --dir apps/web typecheck
types:
	PYTHONPATH=services/api uv run python scripts/export_openapi.py
	pnpm --dir apps/web generate:api
up:
	docker compose up --build

.PHONY: knowledge-audit knowledge-index retrieval-eval
knowledge-audit:
	PYTHONPATH=services/api uv run python -m support_api.knowledge audit
knowledge-index:
	PYTHONPATH=services/api uv run python -m support_api.knowledge index
retrieval-eval:
	PYTHONPATH=services/api uv run python -m support_api.knowledge.evaluate --require-targets
