FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# git is required to clone repositories being indexed
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app app
COPY migrations migrations
COPY alembic.ini .
RUN mkdir -p /data/workspace && chown -R app:app /data /app
USER app
ENV ENVIRONMENT=production WORKSPACE_DIR=/data/workspace
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
# One worker on purpose: background indexing jobs, the login limiter and the search cache are in-process.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
