FROM python:3.12-slim
RUN pip install --no-cache-dir mcp==1.2.0
WORKDIR /app
COPY server.py /app/server.py
ENV ISU_DB_PATH=/data/desk.sqlite3
ENTRYPOINT ["python", "/app/server.py"]
