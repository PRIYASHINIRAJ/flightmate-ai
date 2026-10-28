# Backend for Render: Python for the API, Node for the weather MCP (npx).
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the weather MCP once at build time instead of on every request.
RUN npm install -g @dangahagan/weather-mcp@latest

COPY api.py server.py ./

# Render sets PORT.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
