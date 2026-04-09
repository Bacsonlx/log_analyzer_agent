# 实时链路：重命名 + 时间线内嵌 ASR 记录

**日期**: 2026-04-08
**范围**: `web-diagnostic`（`server.py`、`templates/index.js`、`idle.js`、`report.js`）

## 1. 重命名

| 位置 | 旧值 | 新值 |
|------|------|------|
| `server.py` `_TEMPLATE_PHASES["audio-recognition"]["label"]` | 识别 | 实时链路 |
| `templates/index.js` `TEMPLATES["audio-recognition"].label` | 识别 | 实时链路 |
| `idle.js` `SCENARIO_OPTIONS` | 翻译/ASR | 实时链路 |
| `idle.js` `SCENARIO_TEMPLATE_MAP` key | 翻译/ASR | 实时链路 |

template id `audio-recognition` 保持不变（兼容历史数据）。

## 2. 时间线内嵌 ASR

当前每段录音卡片内是两个独立区域（时间线 + ASR 列表）。改为一条连贯时间线：ASR 句子作为「开始识别」阶段的缩进子节点，位于「开始识别」和「识别结束」之间。

### 布局

```
录音 #1  ej_PHONE00UrkYs7_1775540437               3句 成功
───────────────────────────────────────────────────────
● 选择设备 ✓  13:40:38.100
│  [Record] 设备连接成功
│
● 选择语言 ✓  13:40:38.500
│  [ASR] zh → en
│
● 点击开始 ✓  13:40:39.000
│  [Session] 会话创建成功
│
● 开始识别 ✓  13:40:39.100
│  [ASR] 识别中
│  ├─ ① "你好" → "Hello"              0.8s ✓  13:40:40
│  ├─ ② "今天天气怎么样" → "How is…"   1.2s ✓  13:40:42
│  └─ ③ (空结果)                       0.3s ⚠  13:40:45
│
● 识别结束 ✓  13:41:00.000
│  [ASR] 正常结束，3句
```

### 实现

- `_buildRecordingsHtml` 不再单独渲染 ASR 区域
- 改为调用新方法 `_buildIntegratedTimelineHtml(phases, asrRecords)`：
  - 遍历 phases，正常渲染每个阶段节点
  - 当遇到 name === "开始识别" 且有 asrRecords 时，在该节点后插入 ASR 子项
  - ASR 子项使用缩进样式 + 左侧虚线连接
  - 每句可展开查看 updates 详情
- 卡片头 record_id 显示全量（不截断），便于复制

## 3. 不改动

- 数据结构不变（recordings / asr_records / phases）
- 服务端逻辑不变
- 其他模版不受影响
