.PHONY: install dev test seed record-fixtures demo lint typecheck

install:
	pip install -e ".[dev]"

seed:
	python -m app.db.init_db --reset

dev:
	uvicorn app.api.app:app --reload --port 8000

test:
	pytest -v

record-fixtures:
	python scripts/record_fixtures.py

demo:
	python -m app.main --batch

lint:
	ruff check app tests

typecheck:
	mypy app
