.PHONY: install dev test smoke smoke-live release-gate clean

# Niwa v1 dev harness.

BACKEND_DIR := backend
FRONTEND_DIR := frontend
PYTHON ?= $(shell if [ -x "$$HOME/.niwa/venv/bin/python" ]; then echo "$$HOME/.niwa/venv/bin/python"; elif command -v python3.12 >/dev/null 2>&1; then command -v python3.12; elif command -v python3.11 >/dev/null 2>&1; then command -v python3.11; else command -v python3; fi)

install:
	cd $(BACKEND_DIR) && $(PYTHON) -m pip install -e .[dev]
	cd $(FRONTEND_DIR) && npm install

dev:
	@echo "Starting backend on :8000 and frontend on :5173 (Ctrl-C stops both)"
	cd $(BACKEND_DIR) && python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload & \
		cd $(FRONTEND_DIR) && npm run dev -- --host 127.0.0.1 --port 5173; \
		kill %1 2>/dev/null || true

test:
	cd $(BACKEND_DIR) && $(PYTHON) -m pytest -q
	cd $(FRONTEND_DIR) && npm test -- --run

smoke:
	$(PYTHON) scripts/smoke_v1_1.py

smoke-live:
	scripts/smoke_live.sh

release-gate:
	scripts/clean_machine_gate.sh

clean:
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/**/__pycache__ \
		$(BACKEND_DIR)/*.egg-info \
		$(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist \
		.smoke
