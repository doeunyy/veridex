# syntax=docker/dockerfile:1.6@sha256:ac85f380a63b13dfcefa89046420e1781752bab202122f8f50032edf31be0021
# Pinned official Python 3.13.16 (Debian trixie) and uv 0.12.23 multi-platform manifests.
FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project --compile-bytecode

FROM dependencies AS verified
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
COPY src/ ./src/
RUN python -m compileall -q /app/src
COPY scripts/serve_api.py scripts/container_entrypoint.py scripts/check_container.py ./scripts/
# Named context is independently supplied; no raw repository data is copied.
COPY --from=rag /manifest.json /bundle.json /opt/veridex/rag/
COPY --from=rag /papers/rag_2020.pdf /papers/react_2022.pdf /papers/self_rag_2023.pdf /papers/netmhcpan_2020.pdf /papers/mixmhc2pred_2023.pdf /opt/veridex/rag/papers/
COPY --from=rag /chroma/ /opt/veridex/rag/chroma/
ARG RAG_BUNDLE_SHA256=6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8
ENV RAG_BUNDLE_SHA256=$RAG_BUNDLE_SHA256
RUN python scripts/check_container.py
RUN find /opt/veridex/rag -type d -exec chmod 0555 {} + && find /opt/veridex/rag -type f -exec chmod 0444 {} +

FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS runtime
WORKDIR /app
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_ENV=production PORT=8080
ARG RAG_BUNDLE_SHA256=6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8
ENV RAG_BUNDLE_SHA256=$RAG_BUNDLE_SHA256 DOCUMENTS_DIR=/opt/veridex/rag/papers WORKSPACE_MANIFEST_PATH=/opt/veridex/rag/manifest.json
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=verified /app /app
COPY --from=verified /opt/veridex/rag /opt/veridex/rag
RUN groupadd --gid 10001 veridex && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp/veridex --shell /usr/sbin/nologin veridex
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/venv/bin/python", "/app/scripts/container_entrypoint.py"]
