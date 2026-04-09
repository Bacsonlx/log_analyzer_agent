# History Card Enrichment Design

> 在首页侧栏历史列表中展示丰富的报告摘要信息，让用户无需打开详情即可了解每次诊断的关键结果。

## 背景

当前 `HistoryList` 组件每条卡片仅展示状态图标（勾/叉）、耗时和标题名称，无法快速判断诊断场景类型、可信度评分和各阶段通过情况。用户需要逐条点开才能了解报告质量。

## 目标

- 在不改变侧栏布局（`aside` 约 2/5 宽度）的前提下，紧凑展示 6 项报告信息
- 后端列表 API 增量返回轻量摘要字段，不返回完整 template_data
- 前端卡片重新排版，支持老记录（无 template_data）降级显示

## 方案选型

采用**纯前端扩展 + 后端轻量字段**方案：
- 后端 `_load_history` 新增 3 个字段（`template_id`、`template_label`、`phase_statuses`）
- 前端 `history-list.js` 卡片 HTML 重构为 4 层布局
- 不引入额外网络请求，不返回完整 phases 详情

## 后端改动

### 文件：`server.py` — `_load_history` 函数

在构建每条列表记录时，从存储的 JSON 中提取 `template_data` 摘要：

```python
td = data.get("template_data")
template_id = None
template_label = None
phase_statuses = None
if td and isinstance(td, dict):
    raw_tid = td.get("template")
    template_id = _normalize_template_id(raw_tid) if raw_tid else None
    if template_id:
        template_label = _TEMPLATE_PHASES.get(template_id, {}).get("label")
    phases = td.get("phases", [])
    if phases and isinstance(phases, list):
        phase_statuses = [
            p.get("status", "skipped") for p in phases if isinstance(p, dict)
        ]
```

新增字段追加到返回 dict 中：

| 字段 | 类型 | 说明 |
|------|------|------|
| `template_id` | `str \| None` | 诊断场景 ID，如 `"audio-recognition"` |
| `template_label` | `str \| None` | 场景中文名，如 `"识别"` |
| `phase_statuses` | `list[str] \| None` | 各阶段状态，如 `["success","success","failed","success","skipped"]` |

已有字段 `score`、`cost_usd`、`start_time`、`duration_ms` 等保持不变。

## 前端改动

### 文件：`history-list.js` — `render()` 方法

#### 卡片 4 层布局

```
┌──────────────────────────────────────┐
│ [识别] badge   7.5/10 badge   04-08 │  第 1 行：场景标签 + 可信度 + 日期
│──────────────────────────────────────│
│ ✓ 04-08 15:30 ASR识别失败诊断报告    │  第 2 行：状态图标 + 标题（截断）
│ ●●●○● (hover显示阶段名)    12.3s $0.05│  第 3 行：阶段圆点 + 耗时 + 费用
│ 用户反馈翻译功能无法使用，点击…       │  第 4 行：描述（一行截断）
│                                [🗑]  │  删除按钮（hover 显示）
└──────────────────────────────────────┘
```

#### 各元素样式

| 元素 | Tailwind 类 | 说明 |
|------|-------------|------|
| 场景标签 | `text-[9px] font-bold px-1.5 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary` | 复用 report.js timeline 视图的标签样式 |
| 可信度 badge | 绿(≥7.5) / 黄(≥5) / 红(<5)，`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border` | 复用 report.js 的 `_scoreBadgeHtml` 配色逻辑 |
| 日期 | `text-[10px] text-slate-600 font-mono` | 显示 `MM-DD`，`title` 属性放完整时间 |
| 状态图标 | 绿勾/红叉 `text-lg` | 保持当前逻辑不变 |
| 标题 | `text-xs font-bold text-slate-300 truncate` | 单行截断，可点击打开详情 |
| 阶段圆点 | `w-1.5 h-1.5 rounded-full inline-block` | 绿=success, 红=failed, 黄=warning, 灰=skipped；每个圆点 `title` 属性显示阶段名 |
| 耗时 | `text-[10px] text-slate-600 font-mono` | 如 `12.3s` |
| 费用 | `text-[10px] text-slate-600 font-mono` | 如 `$0.05` |
| 描述 | `text-[11px] text-slate-500 truncate` | 单行截断 |
| 删除 | `opacity-0 group-hover:opacity-100` | hover 显示，保持当前行为 |

#### 阶段圆点颜色映射

```javascript
const dotColor = {
  success: 'bg-neon-green',
  failed:  'bg-accent-red',
  warning: 'bg-accent-yellow',
  skipped: 'bg-slate-600',
};
```

#### 阶段名称 hover 提示

前端通过 `template_id` 查 `TEMPLATES[template_id].phases` 数组，与 `phase_statuses` 按索引一一对应，作为每个圆点的 `title` 属性。若长度不匹配则不显示阶段名。

### 无 template_data 的降级

老记录没有 `template_data` 时（`template_id === null`）：
- 第 1 行：场景标签不显示，可信度和日期仍展示
- 第 3 行：阶段圆点行不渲染，仅显示耗时和费用
- 其余字段正常展示

### 可信度为 null 的降级

如果 `score` 为 `null`（AI 未输出可信度标记的老报告）：
- 可信度 badge 显示 `N/A`，使用 `text-slate-600` 灰色样式

## 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `web-diagnostic/server.py` | 修改 `_load_history`，新增 3 字段提取 |
| `web-diagnostic/frontend/src/components/history-list.js` | 重构卡片 `render()` HTML 和样式 |

## 不涉及

- 列表条数限制（仍 10 条显示、20 条 API）
- 侧栏宽度和位置
- 历史详情加载 (`_loadDetail`) 逻辑
- 分享链接 / 深链接行为
- report.js 报告视图
