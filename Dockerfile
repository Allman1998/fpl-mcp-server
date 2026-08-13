FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip uninstall -y mcp || true
RUN python -m pip install --no-cache-dir "mcp==1.25.0"
RUN python -m pip install --no-cache-dir \
    "fastapi>=0.100.0" \
    "uvicorn>=0.20.0" \
    "httpx>=0.27.0" \
    "playwright>=1.40.0" \
    "pydantic>=2.0.0" \
    "python-multipart>=0.0.9" \
    "beautifulsoup4>=4.12.0"

RUN python -m pip install --no-cache-dir --no-deps .

RUN python -c "from mcp.server.fastmcp import FastMCP; print('FASTmcp 1.25.0 OK')"

RUN playwright install chromium

ENV PYTHONUNBUFFERED=1
ENV PORT=10000

EXPOSE 10000

CMD ["python", "-m", "fpl_server.remote_main"]