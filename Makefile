PYTHON ?= .venv/bin/python

.PHONY: format check test-db test-models migrate

format:
	$(PYTHON) -m ruff check --select I --fix .
	$(PYTHON) -m ruff format .

check:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

test-db:
	$(PYTHON) -m unittest discover -s moseby/db/tests -v

test-models:
	$(PYTHON) -m unittest discover -s moseby/runtime/tests -v

migrate:
	$(PYTHON) -m alembic upgrade head
