# Stage 1: Build React frontend
FROM node:22-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python app (stdlib only, no extra deps)
FROM python:3.12.8-slim
WORKDIR /app
COPY backend/ /app/backend/
COPY db/ /app/db/
COPY config/ /app/config/

# Copy React entry point (used by vite build)
COPY frontend/index.html /app/frontend/index.html

# Copy legacy frontend (vanilla JS fallback)
COPY frontend/index-legacy.html /app/frontend/index-legacy.html
COPY frontend/static/ /app/frontend/static/

# Copy React build output (this is what gets served)
COPY --from=frontend-build /build/dist/ /app/frontend/dist/

# Defaults — override via env at runtime.
ENV NIWA_APP_HOST=0.0.0.0 \
    NIWA_APP_PORT=8080 \
    NIWA_DB_PATH=/data/niwa.sqlite3

EXPOSE 8080
CMD ["python", "/app/backend/app.py"]
