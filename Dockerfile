# Kairoz HR Management — production image (AWS ECS Fargate, linux/arm64 or amd64).
# Build:  docker build -t hr-management .
# Run:    docker run -p 8000:8000 --env-file .env hr-management
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels ".[aws,postgres]"

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HRM_ENVIRONMENT=production HRM_DATA_DIR=/tmp/hrm PORT=8000 WEB_CONCURRENCY=2
RUN useradd --create-home --uid 10001 app
COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels hr-management[aws,postgres] && rm -rf /wheels
USER app
WORKDIR /home/app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)" || exit 1
# Schema creation/upgrades are idempotent and run in create_app(); several tasks starting together is safe.
CMD ["sh", "-c", "uvicorn hr_management.web:create_app --factory --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
