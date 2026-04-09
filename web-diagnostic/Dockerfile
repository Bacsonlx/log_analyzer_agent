# syntax=docker/dockerfile:1
#
# Web Diagnostic — 多阶段构建
#
# Build from repository root:
#   docker build -f web-diagnostic/Dockerfile -t web-diagnostic:local .
#
# With Claude Code CLI:
#   docker build -f web-diagnostic/Dockerfile --build-arg INSTALL_CLAUDE=1 -t web-diagnostic:with-claude .
#
# If the SPA UI still looks old after rebuild: (1) docker rm -f <name> && run the new IMAGE_ID,
#   (2) docker build ... --no-cache, or (3) bust the frontend layer:
#   --build-arg FRONTEND_CACHE_BUST=$(git rev-parse HEAD)

# ── Stage 1: 前端构建 ──
FROM node:20-alpine AS frontend-build

WORKDIR /build
COPY web-diagnostic/frontend/package.json web-diagnostic/frontend/package-lock.json* ./
RUN npm ci --ignore-scripts

# Optional: pass a new value to force npm run build when Docker reuses a stale COPY layer.
ARG FRONTEND_CACHE_BUST
RUN echo "frontend cache bust: ${FRONTEND_CACHE_BUST:-none}"

COPY web-diagnostic/frontend/ ./
RUN npm run build

# ── Stage 2: Python 运行时 ──
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

ARG INSTALL_CLAUDE=0
ENV PATH="/root/.local/bin:/usr/local/bin:${PATH}"
RUN if [ "$INSTALL_CLAUDE" = "1" ]; then \
      curl -fsSL https://claude.ai/install.sh | bash; \
    fi

WORKDIR /workspace
ENV WORKSPACE_ROOT=/workspace
ENV PROJECT_ROOT=/workspace
ENV WEB_DIAGNOSTIC_SKIP_CLAUDE=1
ENV PYTHONUNBUFFERED=1

COPY tools/log-analyzer /workspace/tools/log-analyzer
RUN chmod +x /workspace/tools/log-analyzer/run.sh \
    && rm -rf /workspace/tools/log-analyzer/.venv \
    && python3 -m venv /workspace/tools/log-analyzer/.venv \
    && /workspace/tools/log-analyzer/.venv/bin/pip install \
        --no-cache-dir --root-user-action=ignore \
        -r /workspace/tools/log-analyzer/requirements.txt

COPY web-diagnostic/server.py /workspace/web-diagnostic/server.py
COPY web-diagnostic/claude_runner.py /workspace/web-diagnostic/claude_runner.py
COPY web-diagnostic/start.sh /workspace/web-diagnostic/start.sh
COPY web-diagnostic/requirements.txt /workspace/web-diagnostic/requirements.txt
COPY web-diagnostic/static /workspace/web-diagnostic/static

COPY --from=frontend-build /build/dist /workspace/web-diagnostic/frontend/dist
# 若 Stage1 未产出 dist/index.html，此处失败可避免运行期静默回退到 static/
RUN test -f /workspace/web-diagnostic/frontend/dist/index.html

RUN chmod +x /workspace/web-diagnostic/start.sh \
    && rm -rf /workspace/web-diagnostic/.venv \
    && python3 -m venv /workspace/web-diagnostic/.venv \
    && /workspace/web-diagnostic/.venv/bin/pip install \
        --no-cache-dir --root-user-action=ignore \
        -r /workspace/web-diagnostic/requirements.txt

RUN mkdir -p /workspace/tools/log-analyzer/data \
    && mkdir -p /workspace/web-diagnostic/data/history

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["/workspace/web-diagnostic/start.sh"]
