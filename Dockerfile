# syntax=docker/dockerfile:1.6@sha256:ac85f380a63b13dfcefa89046420e1781752bab202122f8f50032edf31be0021
# Veridex v2: FastAPI + LangGraph supervisor + local MCP servers + baked Corpus v3 index.
# Multi-stage, pinned Python 3.13.16 (Debian trixie), non-root, binds Cloud Run's $PORT.

FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile --prefix=/install -r requirements.txt

FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
WORKDIR /app
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ANONYMIZED_TELEMETRY=False \
    APP_ENV=production \
    PORT=8080 \
    STATE_BACKEND=firestore \
    CORPUS_MANIFEST_PATH=/app/data/corpus_v3/papers.json \
    DOCUMENTS_DIR=/app/corpus/papers \
    CHROMA_PERSIST_DIR=/app/corpus/chroma \
    CATALOG_PATH=/app/corpus/catalog.db
COPY --from=build /install /usr/local

COPY src/ ./src/
COPY scripts/serve_api.py scripts/check_bundle.py ./scripts/
COPY data/corpus_v3/papers.json ./data/corpus_v3/papers.json
# Corpus v3 bundle built by scripts/corpus_v3.py (download, plan, build, catalog).
COPY .artifacts/corpus_v3/papers/ ./corpus/papers/
COPY .artifacts/corpus_v3/chroma/ ./corpus/chroma/
COPY .artifacts/corpus_v3/catalog.db ./corpus/catalog.db

# Fail the build, not the first request, if the bundle is incomplete or altered.
RUN python -m compileall -q src && python scripts/check_bundle.py

# Chroma writes its SQLite journal next to the index, so only that directory is writable.
RUN groupadd --gid 10001 veridex \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin veridex \
    && chown -R veridex:veridex /app/corpus/chroma
USER 10001:10001
EXPOSE 8080
CMD ["python", "scripts/serve_api.py"]
