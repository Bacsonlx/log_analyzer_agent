#!/bin/bash
# 知识库有效性验证脚本
# 检查知识库中引用的 TAG 是否仍存在于代码中，以及知识库是否长期未更新。
#
# 用法:
#   ./verify-knowledge.sh              # 默认扫描项目根目录
#   ./verify-knowledge.sh /path/to/project  # 指定项目根目录
#   ./verify-knowledge.sh --stale-days 90   # 自定义过期天数（默认 180）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KNOWLEDGE_DIR="$SCRIPT_DIR/knowledge"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# 默认参数
PROJECT_ROOT=""
STALE_DAYS=180

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --stale-days)
            STALE_DAYS="$2"
            shift 2
            ;;
        *)
            PROJECT_ROOT="$1"
            shift
            ;;
    esac
done

# 自动检测项目根目录
# .ai-config 是独立 git 仓库，不能用 git rev-parse。
# 向上查找包含 bluetooth/ 等组件目录的层级作为主项目根目录。
if [ -z "$PROJECT_ROOT" ]; then
    _dir="$SCRIPT_DIR"
    while [ "$_dir" != "/" ]; do
        if [ -d "$_dir/bluetooth" ] && [ -d "$_dir/mqtt" ]; then
            PROJECT_ROOT="$_dir"
            break
        fi
        _dir="$(dirname "$_dir")"
    done
    if [ -z "$PROJECT_ROOT" ]; then
        echo "ERROR: 无法自动检测项目根目录，请手动指定: ./verify-knowledge.sh /path/to/project" >&2
        exit 1
    fi
fi

# 检查 Python 环境
if [ ! -f "$VENV_PYTHON" ]; then
    echo "ERROR: 未找到 venv，请先运行 run.sh 初始化环境" >&2
    exit 1
fi

# 用 Python 执行验证逻辑（复用 tag_scanner.py）
"$VENV_PYTHON" -c "
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

script_dir = '$SCRIPT_DIR'
knowledge_dir = '$KNOWLEDGE_DIR'
project_root = '$PROJECT_ROOT'
stale_days = $STALE_DAYS

sys.path.insert(0, script_dir)
from tag_scanner import scan_tags, load_index, save_index

# 1. 获取或构建 TAG 索引
index_path = os.path.join(script_dir, 'data', 'tag-index.json')
index = load_index(index_path)
if index is None:
    print('[verify] TAG 索引不存在，正在构建...')
    index = scan_tags(project_root)
    save_index(index, index_path)
    print(f'[verify] 索引构建完成: {index[\"meta\"][\"total_tags\"]} TAGs')

all_tags = set(index.get('tags', {}).keys())
print(f'[verify] 代码中共有 {len(all_tags)} 个 TAG')
print()

# 2. 遍历知识库
has_issue = False
total_tags_checked = 0
missing_tags_total = 0
stale_files = []
today = datetime.now()

for fname in sorted(os.listdir(knowledge_dir)):
    if not fname.endswith('.json'):
        continue

    fpath = os.path.join(knowledge_dir, fname)
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    kb_name = data.get('name', fname)
    kb_id = data.get('id', fname)

    # 检查 _meta
    meta = data.get('_meta', {})
    updated = meta.get('updated', '')
    sdk_version = meta.get('sdk_version', 'unknown')

    # 检查过期
    if updated:
        try:
            updated_date = datetime.strptime(updated, '%Y-%m-%d')
            days_since = (today - updated_date).days
            if days_since > stale_days:
                stale_files.append((fname, kb_name, updated, days_since, sdk_version))
        except ValueError:
            stale_files.append((fname, kb_name, updated, -1, sdk_version))
    else:
        stale_files.append((fname, kb_name, '(无日期)', -1, sdk_version))

    # 跳过 error-codes（无 TAG 引用）
    primary = data.get('primary_tags', [])
    secondary = data.get('secondary_tags', [])
    if not primary and not secondary:
        continue

    # 检查 TAG 有效性
    all_kb_tags = primary + secondary
    total_tags_checked += len(all_kb_tags)
    missing = [t for t in all_kb_tags if t not in all_tags]

    if missing:
        has_issue = True
        missing_tags_total += len(missing)
        print(f'[{kb_id}] {kb_name}')
        for t in missing:
            tag_type = 'primary' if t in primary else 'secondary'
            print(f'  MISSING ({tag_type}): {t}')
        print()

# 3. 输出过期知识库
if stale_files:
    print('--- 过期知识库 ---')
    for fname, name, updated, days, ver in stale_files:
        if days < 0:
            print(f'  {fname}: {name} — 更新日期异常 ({updated}), sdk={ver}')
        else:
            print(f'  {fname}: {name} — {days} 天未更新 (上次: {updated}, sdk={ver})')
    print()

# 4. 模块知识引用校验（module_refs）
modules_dir = os.path.join(knowledge_dir, 'modules')
module_ref_issues = 0
if os.path.isdir(modules_dir):
    existing_module_files = set()
    for mf in os.listdir(modules_dir):
        if mf.startswith('aibuds-') and mf.endswith('.json'):
            with open(os.path.join(modules_dir, mf), 'r', encoding='utf-8') as mff:
                md = json.load(mff)
                mod_name = md.get('module', '')
                if mod_name:
                    existing_module_files.add(mod_name)

    for fname in sorted(os.listdir(knowledge_dir)):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(knowledge_dir, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        module_refs = data.get('module_refs', [])
        if not module_refs:
            continue
        kb_id = data.get('id', fname)
        missing_refs = [r for r in module_refs if r not in existing_module_files]
        if missing_refs:
            has_issue = True
            module_ref_issues += len(missing_refs)
            print(f'[{kb_id}] module_refs 引用缺失:')
            for r in missing_refs:
                print(f'  MISSING module knowledge: {r}')
            print()
else:
    print('[warn] knowledge/modules/ 目录不存在，跳过模块引用校验')
    print()

# 5. 汇总
print('=' * 50)
print(f'知识库文件数: {len([f for f in os.listdir(knowledge_dir) if f.endswith(\".json\")])}')
print(f'检查 TAG 数: {total_tags_checked}')
print(f'失效 TAG 数: {missing_tags_total}')
print(f'模块引用缺失: {module_ref_issues}')
print(f'过期知识库数: {len(stale_files)}')

if not has_issue and not stale_files:
    print('结果: ALL PASS')
else:
    if missing_tags_total > 0:
        print(f'结果: {missing_tags_total} 个 TAG 需要更新')
    if module_ref_issues > 0:
        print(f'结果: {module_ref_issues} 个模块引用缺失')
    if stale_files:
        print(f'结果: {len(stale_files)} 个知识库超过 {stale_days} 天未更新')
    sys.exit(1)
"
