# Isu lite — portable version for the Niwa pack.
# Single-stage Python with no extra deps (uses stdlib only).
FROM python:3.12-slim

WORKDIR /app
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY db/ /app/db/
COPY config/ /app/config/

# Defaults — override via env at runtime
ENV ISU_HOST=0.0.0.0 \
    ISU_PORT=8080 \
    ISU_DB_PATH=/data/desk.sqlite3

EXPOSE 8080
CMD ["python", "/app/backend/app.py"]
