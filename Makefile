PYTHON ?= python3

.PHONY: install lint format typecheck test run-trader run-telegram run-learning run-openclaw run-web run-frontend migrate up down up-monitoring

install:
	$(PYTHON) -m pip install -e .[dev]

lint:
	ruff check src tests scripts

format:
	ruff check --fix src tests scripts

typecheck:
	mypy src

test:
	pytest -q

run-trader:
	$(PYTHON) -m src.services.trader.__main__

run-telegram:
	$(PYTHON) -m src.services.telegram.__main__

run-learning:
	$(PYTHON) -m src.services.learning.__main__

run-openclaw:
	$(PYTHON) -m src.services.openclaw.__main__

run-web:
	$(PYTHON) -m src.services.web.__main__

run-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

migrate:
	alembic -c alembic/alembic.ini upgrade head

up:
	docker compose up --build

down:
	docker compose down -v

up-monitoring:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up --build
