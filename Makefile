.PHONY: install dev test clean

# Niwa v1 dev harness. Four targets only per PR-V1-01 brief.

BACKEND_DIR := backend
FRONTEND_DIR := frontend

install:
	cd $(BACKEND_DIR) && python3 -m pip install -e .[dev]
	cd $(FRONTEND_DIR) && npm install

dev:
	@echo "Starting backend on :8000 and frontend on :5173 (Ctrl-C stops both)"
	cd $(BACKEND_DIR) && python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload & \
		cd $(FRONTEND_DIR) && npm run dev -- --host 127.0.0.1 --port 5173; \
		kill %1 2>/dev/null || true

test:
	cd $(BACKEND_DIR) && python3 -m pytest -q
	cd $(FRONTEND_DIR) && npm test -- --run

clean:
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/**/__pycache__ \
		$(BACKEND_DIR)/*.egg-info \
		$(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist
