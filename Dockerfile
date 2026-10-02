FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ISSUEOPS_DB_PATH=/app/data/issueops.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system issueops \
    && useradd --system --gid issueops --home-dir /app issueops \
    && mkdir -p /app/data \
    && chown -R issueops:issueops /app

COPY --chown=issueops:issueops . .

USER issueops

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"]

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
