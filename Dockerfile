FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade "mcp>=1.0.0" \
    && python -m pip install --no-cache-dir . \
    && python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP OK')"

RUN playwright install chromium

ENV PYTHONUNBUFFERED=1
ENV PORT=10000

CMD ["python", "-m", "fpl_server.remote_main"]