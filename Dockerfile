FROM python:3.10-slim

RUN pip install --no-cache-dir fastapi uvicorn httpx logfire python-dotenv

WORKDIR /app
COPY mcp_server.py mcp_config.json ./
COPY .env.example .env

EXPOSE 8000

CMD ["uvicorn", "mcp_server:app", "--host", "0.0.0.0", "--port", "8000"]