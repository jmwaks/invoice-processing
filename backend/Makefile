.PHONY: install dev test seed record-fixtures demo lint typecheck

install:
	cd backend && pip install -e ".[dev]"

seed:
	cd backend && python -m app.db.init_db --reset

dev:
	cd backend && uvicorn app.api.app:app --reload --port 8000

test:
	cd backend && pytest -v

record-fixtures:
	cd backend && python scripts/record_fixtures.py

demo:
	cd backend && python -m app.main --batch

lint:
	cd backend && ruff check app tests

typecheck:
	cd backend && mypy app
