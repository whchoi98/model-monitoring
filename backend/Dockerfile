# syntax=docker/dockerfile:1.7
# Bedrock Monitor Backend — FastAPI (Python 3.11 slim, non-root)

# ---- Stage 1: 빌드 (의존성 설치) ----
FROM python:3.11-slim AS build
WORKDIR /build

# 시스템 의존성 — psycopg2-binary가 일부 환경에서 wheel을 못 찾을 때 fallback.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: 런타임 (slim + non-root) ----
FROM python:3.11-slim AS runtime
WORKDIR /app

# 보안: non-root 사용자 (uid 1000) — ECS Fargate에서 root 회피.
RUN useradd --uid 1000 --create-home --shell /bin/bash appuser \
    && apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 빌드 stage에서 의존성 복사 (전역 site-packages 대신 /install 트리 사용).
COPY --from=build /install /usr/local

# 애플리케이션 소스.
COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8000
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check — ECS가 사용하지 않더라도 docker run 시 진단용.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
