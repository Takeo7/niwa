# Niwa app — portable web UI for the Niwa pack.
# Single-stage Python with no extra deps (uses stdlib only).
FROM python:3.12.8-slim

WORKDIR /app
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY db/ /app/db/
COPY config/ /app/config/

# Defaults — override via env at runtime.
# These match the env vars read by backend/app.py.
ENV NIWA_APP_HOST=0.0.0.0 \
    NIWA_APP_PORT=8080 \
    NIWA_DB_PATH=/data/niwa.sqlite3

EXPOSE 8080
CMD ["python", "/app/backend/app.py"]
