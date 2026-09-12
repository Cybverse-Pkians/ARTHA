.PHONY: help install test lint api console customer clean

help:
	@echo "ARTHA — make targets"
	@echo "  install   create the backend venv and install dependencies"
	@echo "  test      run the backend test suite"
	@echo "  lint      ruff + mypy"
	@echo "  api       run the decision service on :8000"
	@echo "  console   run the banker console on :5173"
	@echo "  customer  run the customer app on :5174"

install:
	cd backend && python3 -m venv .venv && \
	  .venv/bin/pip install --upgrade pip && \
	  .venv/bin/pip install -r requirements-dev.txt
	cd console && npm install
	cd customer-app && npm install

test:
	cd backend && .venv/bin/pytest -q

lint:
	cd backend && .venv/bin/ruff check artha tests && .venv/bin/mypy artha

api:
	cd backend && .venv/bin/uvicorn artha.main:app --reload --port 8000

console:
	cd console && npm run dev

customer:
	cd customer-app && npm run dev

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache
	rm -f .harness.html index.html
