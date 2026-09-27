.PHONY: dev seed verify test lint typecheck backend-dev frontend-dev

backend-dev:
	cd backend && uv run uvicorn flooreplay.api:app --reload --port 8000

frontend-dev:
	cd frontend && pnpm dev

dev:
	@echo "Run these in two shells:"
	@echo "  make backend-dev   (API on :8000, needs PostgreSQL)"
	@echo "  make frontend-dev  (Vite on :5173, proxies /api to :8000)"

seed:
	cd backend && uv run python -m flooreplay seed

migrate:
	cd backend && uv run alembic upgrade head

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check src tests
	cd frontend && pnpm lint

typecheck:
	cd backend && uv run mypy
	cd frontend && pnpm build

verify: lint typecheck test
