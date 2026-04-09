#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

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
}

if [ ! -d "$VENV_DIR" ]; then
    PYTHON=$(find_python)
    if [ -z "$PYTHON" ]; then
        echo "ERROR: fastmcp 需要 Python >= 3.10，当前系统未找到合适版本" >&2
        echo "请安装: brew install python@3.12" >&2
        exit 1
    fi
    echo "[log-analyzer] 使用 $PYTHON 创建 venv..." >&2
    "$PYTHON" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
fi

# Cursor 通过 env 设置 PROJECT_ROOT；Claude Code 等其他环境自动检测
if [ -z "$PROJECT_ROOT" ]; then
    export PROJECT_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$SCRIPT_DIR")")"
fi

# 执行server.py
exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/server.py" "$@"
