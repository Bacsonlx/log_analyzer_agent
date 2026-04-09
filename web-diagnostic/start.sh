#!/bin/bash
#
# DeviceCore AI 诊断 Web 服务 — 一键启动
#
# Docker：镜像 CMD 即本脚本（预建 web-diagnostic/.venv）；Claude 子进程 MCP 使用
#   /workspace/tools/log-analyzer/run.sh（见 docker/workspace.mcp.json）。
#
# 用法:
#   ./start.sh              # 默认 0.0.0.0:8080
#   ./start.sh --port 9000  # 指定端口
#

set -e

# macOS Homebrew 环境（确保 claude / node 等在 PATH 中）
if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

# pyenv 支持
if command -v pyenv &>/dev/null; then
    eval "$(pyenv init -)"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export WORKSPACE_ROOT="$REPO_ROOT"

# Claude Code CLI 在 WORKSPACE_ROOT 下读取 .mcp.json；缺失则无法注册 log-analyzer
MCP_JSON="$REPO_ROOT/.mcp.json"
MCP_TEMPLATE="$REPO_ROOT/.ai-config/claude-code/mcp.json"
if [ ! -f "$MCP_JSON" ] && [ -f "$MCP_TEMPLATE" ]; then
    echo "[Web-Diagnostic] 未发现 .mcp.json，已链接 -> .ai-config/claude-code/mcp.json"
    ln -sf ".ai-config/claude-code/mcp.json" "$MCP_JSON"
elif [ ! -f "$MCP_JSON" ]; then
    echo "[Web-Diagnostic] WARNING: 未找到 $MCP_JSON，且不存在 $MCP_TEMPLATE" >&2
    echo "  Claude 子进程将无法加载 MCP（search_logs 等工具不可用）。请运行: ./ai-setup.sh --tool claude-code" >&2
fi

VENV_DIR="$SCRIPT_DIR/.venv"
PORT=8080

# 加载 .env 文件（SSO_USER_TOKEN 等配置）
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    echo "[Web-Diagnostic] 加载 .env 配置..."
    set -a
    source "$ENV_FILE"
    set +a
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

find_python() {
    for py in python3.13 python3.12 python3.11 python3.10; do
        if command -v "$py" &>/dev/null; then
            echo "$py"
            return
        fi
    done
    if command -v python3 &>/dev/null; then
        local ok
        ok=$(python3 -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>/dev/null)
        if [ "$ok" = "1" ]; then
            echo "python3"
            return
        fi
    fi
    # PATH 未含 Homebrew 时（如从 GUI/Cursor 启动终端）：试常见绝对路径
    for c in \
        /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
        /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3.10 \
        /usr/local/opt/python@3.12/bin/python3.12 /usr/local/opt/python@3.11/bin/python3.11 \
        /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10
    do
        if [ -x "$c" ] && "$c" -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
            echo "$c"
            return
        fi
    done
}

if [ ! -d "$VENV_DIR" ]; then
    PYTHON=$(find_python)
    if [ -z "$PYTHON" ]; then
        echo "ERROR: 需要 Python >= 3.10，未找到可用的解释器。" >&2
        if command -v python3 &>/dev/null; then
            echo "  当前 \`python3\` -> $(command -v python3)，版本 $(python3 -V 2>&1)（需 >= 3.10）。" >&2
        else
            echo "  当前 PATH 中无 \`python3\`，且未在常见路径发现 Home/apt 安装的 3.10+。" >&2
        fi
        echo "  macOS: brew install python@3.12，并在本终端执行: eval \"\$(/opt/homebrew/bin/brew shellenv)\"" >&2
        echo "  Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip（或 python3.12-venv）" >&2
        echo "  或使用本仓库 Docker 镜像。" >&2
        exit 1
    fi
    echo "[Web-Diagnostic] 使用 $PYTHON 创建 venv..."
    "$PYTHON" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip -q
fi

echo "[Web-Diagnostic] 同步依赖..."
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q

# ── 前端构建（frontend/dist 不存在或 src 有更新时自动构建）──
FRONTEND_DIR="$SCRIPT_DIR/frontend"
FRONTEND_DIST="$FRONTEND_DIR/dist"
if [ -f "$FRONTEND_DIR/package.json" ]; then
    NEED_BUILD=0
    if [ ! -d "$FRONTEND_DIST" ]; then
        NEED_BUILD=1
    elif [ -n "$(find "$FRONTEND_DIR/src" -newer "$FRONTEND_DIST/index.html" -print -quit 2>/dev/null)" ]; then
        NEED_BUILD=1
    fi
    if [ "$NEED_BUILD" = "1" ]; then
        echo "[Web-Diagnostic] 构建前端..."
        if ! command -v node &>/dev/null; then
            echo "WARNING: node 未找到，跳过前端构建（将回退到 static/index.html）" >&2
        else
            (cd "$FRONTEND_DIR" && npm install --silent 2>/dev/null && npm run build --silent) || {
                echo "WARNING: 前端构建失败，将回退到 static/index.html" >&2
            }
        fi
    else
        echo "[Web-Diagnostic] 前端已构建（frontend/dist）"
    fi
elif [ -d "$FRONTEND_DIST" ] && [ -f "$FRONTEND_DIST/index.html" ]; then
    # Docker 等多阶段镜像通常只带入 dist，不含 package.json
    echo "[Web-Diagnostic] 使用已构建的前端资源（frontend/dist，跳过 npm build）"
else
    echo "[Web-Diagnostic] 未检测到可构建或可加载的前端，HTTP / 将回退到 static/index.html"
fi

if ! command -v claude &>/dev/null; then
    echo "WARNING: claude 命令未找到，请确认 Claude Code 已安装" >&2
fi

echo ""
echo "  DeviceCore AI 诊断"
echo "  http://0.0.0.0:$PORT"
echo ""

exec "$VENV_DIR/bin/uvicorn" server:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --app-dir "$SCRIPT_DIR"
