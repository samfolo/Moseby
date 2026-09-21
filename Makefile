PYTHON ?= .venv/bin/python

.PHONY: format check test-db test-models test-contracts test-inference test-agents test-tools migrate

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

test-contracts:
	$(PYTHON) -m unittest discover -s moseby/contracts/tests -v

test-inference:
	$(PYTHON) -m unittest discover -s moseby/inference/tests -v

test-agents:
	$(PYTHON) -m unittest discover -s moseby/agents/tests -v

test-tools:
	$(PYTHON) -m unittest discover -s moseby/tools/tests -v

migrate:
	$(PYTHON) -m alembic upgrade head
