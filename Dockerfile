# Image cho Proxy Server dịch thuật (không chứa desktop app).
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY server/ ./server/
# server/__init__.py nạp .env qua loader này.
COPY src/__init__.py src/env_file.py ./src/

EXPOSE 8000

CMD ["uvicorn", "server.proxy_server:app", "--host", "0.0.0.0", "--port", "8000"]
