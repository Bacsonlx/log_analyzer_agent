# 提取日志查看器 + ASR 服务端解析 设计文档

**日期：** 2026-04-07  
**状态：** 已批准，待实现

---

## 背景与目标

在已有的诊断报告模版系统（时间线 + Markdown 双模式）基础上，补充两个功能：

1. **通用：提取日志查看与下载** — 诊断过程中 AI 调用 `extract_aibuds_logs` 所产生的提取文件，在结果页中可内嵌查看全量内容，也可下载。适用于所有模版。

2. **ASR 模版专属：服务端二次提取 + asr_records 解析** — 从全量 AIBuds 提取文件中自动过滤 `[AIBuds_ASR]` 行生成子文件，并用 Python 正则解析为结构化 `asr_records`，不再依赖 AI 输出此字段。

---

## 数据结构

### history JSON 新增字段

```json
{
  "extracted_files": [
    {
      "path": "tools/log-analyzer/data/aiBuds__20260407_164023.log",
      "name": "全量提取",
      "type": "full",
      "size_kb": 351.2
    },
    {
      "path": "tools/log-analyzer/data/aiBuds_ASR_20260407_164025.log",
      "name": "ASR提取",
      "type": "asr",
      "size_kb": 48.6
    }
  ]
}
```

`type` 取值：`full`（全量 AIBuds 提取）/ `asr`（ASR 二次提取子文件）

### WebSocket result 消息新增字段

```json
{
  "type": "result",
  "final_text": "...",
  "template_data": { ... },
  "extracted_files": [ ... ]
}
```

---

## 架构

```
[_run_task 流式循环]
  └─ 拦截 tool_result 事件（role=user, tool_result 非空）
  └─ _EXTRACT_FILE_RE 正则匹配 "输出文件: /path/to/aiBuds*.log"
  └─ 捕获 file_path → extracted_files 列表
  └─ 若 task.template ∈ {audio-recognition, translation}:
       → _create_asr_subfile(file_path) → asr_path
       → extracted_files.append(asr_path)
       → _parse_asr_records(asr_path) → template_data.asr_records
         ↓
[_save_history] → 存入 extracted_files 字段
[result WS 消息] → 附带 extracted_files
         ↓
[main.js] → resultMeta.extracted_files
         ↓
[report.js _buildExtractedFilesHtml(files)]
  └─ 所有模版结果页均显示「提取日志」区块
  └─ 懒加载：点击「查看」才请求文件内容
  └─ 下载：window.open('/api/extracted-file?path=...&dl=1')
```

---

## 后端实现细节

### 1. 捕获提取文件路径

```python
_EXTRACT_FILE_RE = re.compile(r'输出文件[：:]\s*(.+?\.log)', re.MULTILINE)
```

在 `_run_task` 流式循环中，检测 `event.role == "user" and event.tool_result`：

```python
m = _EXTRACT_FILE_RE.search(event.tool_result)
if m:
    raw_path = m.group(1).strip().split(' ')[0]  # 去掉 "(196.8KB)"
    # 存为相对于 WORKSPACE 的路径
    rel = Path(raw_path).relative_to(Path(WORKSPACE))
    extracted_files.append({
        "path": str(rel),
        "name": "全量提取",
        "type": "full",
        "size_kb": round(Path(raw_path).stat().st_size / 1024, 1)
    })
```

### 2. ASR 二次提取

```python
def _create_asr_subfile(full_log_path: str) -> str | None:
    """从全量 AIBuds 日志中过滤 [AIBuds_ASR] 行，保存为子文件。"""
    src = Path(full_log_path)
    if not src.is_file():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = src.parent / f"aiBuds_ASR_{ts}.log"
    lines = [l for l in src.read_text(encoding="utf-8", errors="replace").splitlines()
             if "[AIBuds_ASR]" in l]
    dest.write_text("\n".join(lines), encoding="utf-8")
    return str(dest)
```

### 3. ASR records 服务端解析

```python
def _parse_asr_records(asr_log_path: str) -> list[dict]:
    """解析 ASR 日志文件，按 requestId 分组生成结构化记录。"""
```

解析规则：

| 日志模式 | 提取字段 |
|---------|---------|
| `Received - Start - {rid}` | `request_id`, `start_time` |
| `asr - Update - {rid} - {text}` | `updates`（相邻重复去重） |
| `Start sending to the mini-program.*asr: {text}, translate: {t}` | `final_text`, `translation` |
| `ASRTask ended.*Request ID: {rid}, Error: {err}` | `end_time`, `error`, `status=error` |
| `Received cloud End duration：{ms}` | `duration_ms`（关联最近一条记录） |
| `asr & translate All data is empty.*requestId: {rid}` | `status=empty` |

`status` 默认 `success`，有 empty 标志覆盖为 `empty`，Error 非 None 覆盖为 `error`。

### 4. `/api/extracted-file` 端点

```
GET /api/extracted-file?path=<relative_path>
  → { "content": "<file text>", "size_kb": 351.2 }

GET /api/extracted-file?path=<relative_path>&dl=1
  → FileResponse（触发下载）
```

安全：路径白名单限制在 `tools/log-analyzer/data/` 目录内，拒绝 `..` 路径穿越。

### 5. AI prompt 简化

从 `_build_template_prompt()` 中移除 `asr_records` 相关格式要求（改为服务端解析，不再让 AI 输出此字段）。

---

## 前端实现细节

### main.js

实时结果和历史记录加载均存储 `extracted_files`：

```javascript
store.set('resultMeta', {
  ...existingFields,
  extracted_files: msg.extracted_files || [],
});
```

### report.js

新增共用方法 `_buildExtractedFilesHtml(files)`，在 `_renderMarkdown()` 和 `_renderTimeline()` 的操作按钮上方调用。

**区块结构（`extracted_files` 非空时显示）：**

```html
<div>  <!-- 标题：📄 提取日志（N 个文件） -->
  <details>  <!-- 每个文件一个 details -->
    <summary>  <!-- 文件名 · 大小 · 类型徽章 · [下载] 按钮 -->
    <pre>      <!-- 懒加载内容，首次展开时 fetch /api/extracted-file -->
  </details>
</div>
```

懒加载逻辑在 `onMount()` 中通过 `toggle` 事件监听 `<details>` 展开，首次触发时 fetch 内容填入 `<pre>`。

---

## 关键文件路径

| 文件 | 变更 |
|------|------|
| `web-diagnostic/server.py` | 捕获 tool_result 文件路径；`_create_asr_subfile()`；`_parse_asr_records()`；`/api/extracted-file` 端点；history 新增 `extracted_files`；移除 AI prompt 中 asr_records 要求 |
| `web-diagnostic/frontend/src/main.js` | 存储 `extracted_files` 到 resultMeta |
| `web-diagnostic/frontend/src/components/report.js` | `_buildExtractedFilesHtml()` + 懒加载逻辑 |

---

## 验证方案

1. 提交音频识别场景诊断 → 结果页出现「提取日志（2个文件）」区块（全量 + ASR）
2. 展开文件 → 内容懒加载显示，日志内容可滚动
3. 点「下载」→ 浏览器触发文件下载
4. 非 ASR 场景（如云同步上传）→ 只显示全量提取文件，无 ASR 子文件
5. AI 不输出 asr_records → 服务端解析正确填充 `template_data.asr_records`
6. 历史记录重新打开 → `extracted_files` 正确加载，查看/下载功能正常
