FROM python:3.12-slim
RUN pip install --no-cache-dir mcp==1.2.0 docker==7.1.0
WORKDIR /app
COPY server.py /app/server.py
ENTRYPOINT ["python", "/app/server.py"]
