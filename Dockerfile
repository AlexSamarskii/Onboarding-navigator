FROM python:3.13-slim AS builder
WORKDIR /build
COPY workspace/telegram-rag-bot-src/ /build/
RUN python -m pip install --no-cache-dir build wheel \
    && python -m build --wheel --outdir /dist

FROM python:3.13-slim AS runtime
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --uid 1000 --create-home app
COPY --from=builder /dist/*.whl /app/
RUN python -m pip install --no-cache-dir /app/*.whl
COPY integrations/ /app/integrations/
COPY analytics/ /app/analytics/
COPY config/ /app/config/
COPY deploy/build_config_overlay.py /tmp/build_config_overlay.py
RUN python /tmp/build_config_overlay.py /app/config/config.yaml
RUN rm /tmp/build_config_overlay.py
RUN python -c "import yaml; c=yaml.safe_load(open('/app/config/config.yaml')); assert c['http_server']['port']==8080; assert c['http_server']['enabled'] is True"
RUN mkdir -p /data/analytics /data/faiss \
    && chown -R app:app /app /data
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=6s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5); sys.exit(0 if r.status==200 else 1)" || exit 1
CMD ["python", "-m", "telegram_rag_bot", "run"]
