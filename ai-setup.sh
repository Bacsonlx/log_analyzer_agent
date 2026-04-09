#!/bin/bash
#
# AI 开发工具配置 - 初始化/更新脚本
#
# 支持 Cursor 和 Claude Code 双工具。
# 通过 symlink 映射到工作区根目录，对各 IDE/工具完全透明。
#
# 用法（两种方式均可）:
#   ./ai-setup.sh                     # 从工作区根目录运行
#   .ai-config/ai-setup.sh            # 从 .ai-config 内运行（bootstrap）
#
# 选项:
#   --tool cursor                     # 仅配置 Cursor
#   --tool claude-code                # 仅配置 Claude Code
#   --tool both                       # 同时配置两者
#   --reset                           # 清除并重新拉取
#   --unlink                          # 移除 symlink，恢复原状
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 自动检测运行位置：从 .ai-config 内运行时切到上级目录（工作区根）
if [ "$(basename "$SCRIPT_DIR")" = ".ai-config" ]; then
    WORKSPACE_ROOT="$(dirname "$SCRIPT_DIR")"
else
    WORKSPACE_ROOT="$SCRIPT_DIR"
fi
cd "$WORKSPACE_ROOT"

# ========== 配置项 ==========
AI_CONFIG_REPO="https://registry.code.tuya-inc.top/tuya_os_base_android/common/device-core-ai-toolkit.git"
AI_CONFIG_DIR=".ai-config"
AI_CONFIG_BRANCH="feature/aivoice-team"
# ============================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[AI-Setup]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AI-Setup]${NC} $1"; }
error() { echo -e "${RED}[AI-Setup]${NC} $1"; exit 1; }

remove_existing() {
    local target="$1"
    if [ -L "$target" ]; then
        rm "$target"
    elif [ -d "$target" ]; then
        warn "$target 已存在且不是 symlink，备份到 ${target}.bak"
        mv "$target" "${target}.bak"
    elif [ -f "$target" ]; then
        warn "$target 已存在且不是 symlink，备份到 ${target}.bak"
        mv "$target" "${target}.bak"
    fi
}

do_clone_or_pull() {
    if [ -d "$AI_CONFIG_DIR/.git" ]; then
        info "更新 AI 配置仓库..."
        cd "$AI_CONFIG_DIR"
        git fetch origin
        git checkout "$AI_CONFIG_BRANCH" 2>/dev/null || git checkout -b "$AI_CONFIG_BRANCH" "origin/$AI_CONFIG_BRANCH"
        git pull origin "$AI_CONFIG_BRANCH"
        cd "$WORKSPACE_ROOT"
    else
        info "首次克隆 AI 配置仓库..."
        git clone -b "$AI_CONFIG_BRANCH" "$AI_CONFIG_REPO" "$AI_CONFIG_DIR"
    fi
}

detect_tool() {
    if [ -n "$TOOL_TARGET" ]; then
        echo "$TOOL_TARGET"
        return
    fi
    # 默认配置所有工具，没有副作用且避免环境检测遗漏
    echo "both"
}

link_cursor() {
    remove_existing ".cursor"
    ln -sfn "$AI_CONFIG_DIR/cursor" .cursor
    info "  .cursor -> $AI_CONFIG_DIR/cursor"

    remove_existing ".cursorignore"
    ln -sf "$AI_CONFIG_DIR/cursorignore" .cursorignore
    info "  .cursorignore -> $AI_CONFIG_DIR/cursorignore"
}

link_claude_code() {
    remove_existing ".claude"
    ln -sfn "$AI_CONFIG_DIR/claude-code" .claude
    info "  .claude -> $AI_CONFIG_DIR/claude-code"

    # MCP 配置：Claude Code 从项目根的 .mcp.json 读取（不是 .claude/settings.json）
    remove_existing ".mcp.json"
    ln -sf "$AI_CONFIG_DIR/claude-code/mcp.json" .mcp.json
    info "  .mcp.json -> $AI_CONFIG_DIR/claude-code/mcp.json"

    # 子目录 AGENTS.md → CLAUDE.md 符号链接（Claude Code 自动加载子目录 CLAUDE.md）
    # 跳过根目录，因为 .claude/CLAUDE.md 已提供根级上下文
    find . -mindepth 2 -name "AGENTS.md" -not -path "./$AI_CONFIG_DIR/*" -not -path "./.git/*" | while read -r agents_file; do
        local dir
        dir=$(dirname "$agents_file")
        if [ ! -e "$dir/CLAUDE.md" ]; then
            ln -sf AGENTS.md "$dir/CLAUDE.md"
            info "  $dir/CLAUDE.md -> AGENTS.md"
        fi
    done
}

do_link() {
    remove_existing "tools"
    ln -sfn "$AI_CONFIG_DIR/tools" tools

    local tool
    tool=$(detect_tool)
    info "配置模式: $tool"
    info "Symlink 创建:"
    info "  tools   -> $AI_CONFIG_DIR/tools"

    case "$tool" in
        cursor)
            link_cursor
            ;;
        claude-code)
            link_claude_code
            ;;
        both)
            link_cursor
            link_claude_code
            ;;
    esac

    info "Symlink 创建完成"
}

do_unlink() {
    for target in .cursor .cursorignore .claude .mcp.json tools; do
        if [ -L "$target" ]; then
            rm "$target"
            info "已移除 symlink: $target"
            if [ -d "${target}.bak" ]; then
                mv "${target}.bak" "$target"
                info "已恢复备份: ${target}.bak -> $target"
            fi
        else
            [ -e "$target" ] && warn "$target 不是 symlink，跳过"
        fi
    done

    # 清理 AGENTS.md → CLAUDE.md 符号链接
    find . -name "CLAUDE.md" -type l -not -path "./$AI_CONFIG_DIR/*" | while read -r claude_file; do
        local link_target
        link_target=$(readlink "$claude_file")
        if [ "$link_target" = "AGENTS.md" ]; then
            rm "$claude_file"
            info "已移除 symlink: $claude_file"
        fi
    done
}

do_reset() {
    warn "清除 AI 配置..."
    do_unlink
    if [ -d "$AI_CONFIG_DIR" ]; then
        rm -rf "$AI_CONFIG_DIR"
        info "已删除 $AI_CONFIG_DIR"
    fi
    do_clone_or_pull
    do_link
}

install_deps() {
    if [ -f "$AI_CONFIG_DIR/tools/log-analyzer/requirements.txt" ]; then
        info "安装 Python 依赖..."
        pip3 install -r "$AI_CONFIG_DIR/tools/log-analyzer/requirements.txt" -q 2>/dev/null || \
            warn "Python 依赖安装失败，请手动执行: pip3 install -r tools/log-analyzer/requirements.txt"
    fi
}

check_gitignore() {
    local needs_update=false
    for entry in ".ai-config/" ".cursor" ".cursorignore" ".claude" ".mcp.json" "tools/"; do
        if ! grep -qxF "$entry" .gitignore 2>/dev/null; then
            needs_update=true
            break
        fi
    done

    if [ "$needs_update" = true ]; then
        warn "建议在 .gitignore 中添加以下条目:"
        echo "  .ai-config/"
        echo "  .cursor"
        echo "  .claude"
        echo "  tools/"
    fi
}

TOOL_TARGET=""
ACTION=""

while [ $# -gt 0 ]; do
    case "$1" in
        --tool)
            TOOL_TARGET="$2"
            shift 2
            ;;
        --reset)
            ACTION="reset"
            shift
            ;;
        --unlink)
            ACTION="unlink"
            shift
            ;;
        --verify)
            ACTION="verify"
            shift
            ;;
        --help|-h)
            echo "用法: ./ai-setup.sh [选项]"
            echo ""
            echo "选项:"
            echo "  (无)                    自动检测工具并配置"
            echo "  --tool cursor           仅配置 Cursor"
            echo "  --tool claude-code      仅配置 Claude Code"
            echo "  --tool both             同时配置两者"
            echo "  --reset                 清除并重新拉取"
            echo "  --unlink                移除 symlink，恢复原状"
            echo "  --verify                自检：验证配置完整性"
            echo "  --help                  显示帮助"
            exit 0
            ;;
        *)
            error "未知参数: $1（使用 --help 查看帮助）"
            ;;
    esac
done

do_verify() {
    local pass=0
    local warn_count=0
    local fail=0

    _pass() { echo -e "  ${GREEN}[PASS]${NC} $1"; pass=$((pass + 1)); }
    _warn_v() { echo -e "  ${YELLOW}[WARN]${NC} $1"; warn_count=$((warn_count + 1)); }
    _fail() { echo -e "  ${RED}[FAIL]${NC} $1"; fail=$((fail + 1)); }

    info "开始自检..."
    echo ""

    # 1. 符号链接
    echo "── 符号链接 ──"
    for link_pair in ".claude:$AI_CONFIG_DIR/claude-code" ".cursor:$AI_CONFIG_DIR/cursor" ".mcp.json:$AI_CONFIG_DIR/claude-code/mcp.json" "tools:$AI_CONFIG_DIR/tools"; do
        local link_name="${link_pair%%:*}"
        local link_target="${link_pair##*:}"
        if [ -L "$link_name" ]; then
            local actual_target
            actual_target=$(readlink "$link_name")
            if [ "$actual_target" = "$link_target" ]; then
                _pass "$link_name -> $link_target"
            else
                _warn_v "$link_name 指向 $actual_target（期望 $link_target）"
            fi
        elif [ -e "$link_name" ]; then
            _warn_v "$link_name 存在但不是 symlink"
        else
            _fail "$link_name 不存在"
        fi
    done
    echo ""

    # 2. 子目录 CLAUDE.md symlink
    echo "── 组件文档 ──"
    local agents_count=0
    local claude_link_count=0
    local claude_missing=0
    # Avoid bash-only "done < <(find ...)" (fails under sh/dash); keep loop in this shell for counters.
    local agents_tmp
    agents_tmp=$(mktemp "${TMPDIR:-/tmp}/ai-setup.agents.XXXXXX")
    find . -mindepth 2 -name "AGENTS.md" -not -path "./$AI_CONFIG_DIR/*" -not -path "./.git/*" 2>/dev/null >"$agents_tmp" || true
    while IFS= read -r agents_file; do
        [ -z "$agents_file" ] && continue
        agents_count=$((agents_count + 1))
        local dir
        dir=$(dirname "$agents_file")
        if [ -L "$dir/CLAUDE.md" ]; then
            claude_link_count=$((claude_link_count + 1))
        elif [ ! -e "$dir/CLAUDE.md" ]; then
            claude_missing=$((claude_missing + 1))
        fi
    done < <(find . -mindepth 2 -name "AGENTS.md" -not -path "./$AI_CONFIG_DIR/*" -not -path "./.git/*" 2>/dev/null)

    if [ "$agents_count" -gt 0 ]; then
        if [ "$claude_missing" -eq 0 ]; then
            _pass "AGENTS.md: $agents_count 个，CLAUDE.md symlink: $claude_link_count 个"
        else
            _warn_v "AGENTS.md: $agents_count 个，缺少 CLAUDE.md symlink: $claude_missing 个"
        fi
    else
        _warn_v "未找到组件级 AGENTS.md"
    fi
    echo ""

    # 3. Python 环境
    echo "── Python 环境 ──"
    local venv_python="$AI_CONFIG_DIR/tools/log-analyzer/.venv/bin/python"
    if [ -f "$venv_python" ]; then
        local py_version
        py_version=$("$venv_python" --version 2>&1)
        _pass "venv: $py_version"

        # fastmcp
        if "$venv_python" -c "import fastmcp" 2>/dev/null; then
            _pass "fastmcp: 已安装"
        else
            _fail "fastmcp: 未安装"
        fi
    else
        _warn_v "venv 未创建（首次使用 MCP 工具时会自动创建）"
    fi
    echo ""

    # 4. 系统依赖
    echo "── 系统依赖 ──"
    if command -v jq &>/dev/null; then
        _pass "jq: $(jq --version 2>&1)"
    else
        _fail "jq: 未安装（Hook 脚本依赖，请执行 brew install jq）"
    fi

    if command -v groovy &>/dev/null; then
        _pass "groovy: 已安装"
    else
        _warn_v "groovy: 未安装（分支管理脚本依赖，brew install groovy）"
    fi
    echo ""

    # 5. Hook 脚本
    echo "── Hook 脚本 ──"
    local hook_script="$AI_CONFIG_DIR/cursor/hooks/check-api-boundary.sh"
    if [ -f "$hook_script" ]; then
        if [ -x "$hook_script" ]; then
            _pass "check-api-boundary.sh: 可执行"
        else
            _warn_v "check-api-boundary.sh: 存在但不可执行"
        fi
    else
        _fail "check-api-boundary.sh: 文件不存在"
    fi
    echo ""

    # 6. TAG 索引 & 知识库
    echo "── TAG 索引 & 知识库 ──"
    local index_file="$AI_CONFIG_DIR/tools/log-analyzer/data/tag-index.json"
    if [ -f "$index_file" ]; then
        if [ -f "$venv_python" ]; then
            local tag_count
            tag_count=$("$venv_python" -c "import json; idx=json.load(open('$index_file')); print(idx['meta']['total_tags'])" 2>/dev/null || echo "0")
            if [ "$tag_count" -gt 0 ]; then
                _pass "TAG 索引: $tag_count TAGs"
            else
                _warn_v "TAG 索引: 0 TAGs（可能需要重建: build_tag_index）"
            fi
        else
            _pass "TAG 索引: 文件存在"
        fi
    else
        _warn_v "TAG 索引: 未构建（首次使用时会自动构建）"
    fi

    local verify_script="$AI_CONFIG_DIR/tools/log-analyzer/verify-knowledge.sh"
    if [ -f "$verify_script" ] && [ -f "$venv_python" ]; then
        local kb_result
        kb_result=$("$verify_script" 2>&1 | tail -3)
        local missing
        missing=$(echo "$kb_result" | grep "失效 TAG 数" | awk '{print $NF}')
        if [ "$missing" = "0" ]; then
            _pass "知识库: 所有 TAG 有效"
        else
            _warn_v "知识库: ${missing:-?} 个 TAG 失效（运行 verify-knowledge.sh 查看详情）"
        fi
    else
        _warn_v "知识库验证: 跳过（缺少 venv 或验证脚本）"
    fi
    echo ""

    # 汇总
    echo "══════════════════════════════════════"
    echo -e "  ${GREEN}PASS${NC}: $pass    ${YELLOW}WARN${NC}: $warn_count    ${RED}FAIL${NC}: $fail"
    echo "══════════════════════════════════════"

    if [ "$fail" -gt 0 ]; then
        echo ""
        error "存在 $fail 项检查失败，请修复后重试"
    fi
}

case "${ACTION:-}" in
    reset)
        do_reset
        install_deps
        ;;
    unlink)
        do_unlink
        ;;
    verify)
        do_verify
        ;;
    *)
        do_clone_or_pull
        do_link
        install_deps
        check_gitignore
        ;;
esac

info "完成"
