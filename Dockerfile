FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN playwright install chromium

ENV PYTHONUNBUFFERED=1
ENV PORT=10000

CMD ["python", "-m", "fpl_server.remote_main"]