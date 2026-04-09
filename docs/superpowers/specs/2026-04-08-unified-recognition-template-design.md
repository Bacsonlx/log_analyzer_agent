# 诊断报告模版：识别场景统一（audio-recognition）

**日期**: 2026-04-08  
**范围**: `web-diagnostic`（`server.py`、前端模版与场景映射）

## 1. 背景与问题

报告模版中同时存在「音频识别流程」（`audio-recognition`）与「翻译/ASR」（`translation`）。二者在能力上重叠：均依赖 `[AIBuds_ASR]` 与 `asr_records`，服务端对两种 `template` 走同一套 ASR 子文件提取逻辑。双入口容易让使用者在下拉里选混，且维护两份 phases 不必要。

## 2. 目标

- **单一模版 ID**：只保留 `audio-recognition`，删除 `translation`。
- **统一展示名**：模版标签为 **「识别」**（笼统覆盖实时识别与翻译相关排查）。
- **阶段列表**：采用原 `audio-recognition` 的五步用户操作路径（方案 1）：
  1. 选择设备  
  2. 选择语言  
  3. 点击开始  
  4. 开始识别  
  5. 识别结束  
- **翻译信息**：不单独占 phase 名；继续通过结构化字段 `asr_records[].translation` 呈现。

## 3. 非目标

- 不改变 ASR 日志解析正则与 `asr_records` 字段契约（除非后续单独需求）。
- 不要求迁移或改写历史 Markdown 正文，仅保证历史 `template_data` 可读。

## 4. 行为说明

### 4.1 服务端（`server.py`）

- `_TEMPLATE_PHASES`：移除 `translation` 键；`audio-recognition` 的 `label` 改为 `识别`，`phases` 保持上述五步，`asr_records` 仍为 `True`。
- ASR 子文件生成与 `asr_records` 合并：仅当 `task.template == "audio-recognition"` 时触发（去掉对 `translation` 的并列判断）。
- **自动模版提示**：`auto` 模式下列出的场景列表不再包含 `translation`。
- **历史兼容**：若已保存的 `template_data.template == "translation"`（旧数据），在用于合并服务端 ASR 或前端展示时，**视为** `audio-recognition`（映射表或等价判断一处维护即可，避免历史记录无 meta）。

### 4.2 前端

- `frontend/src/templates/index.js`：删除 `translation`；`audio-recognition` 的 `label` 与 `phases` 与服务端一致。
- `frontend/src/views/idle.js`：`SCENARIO_TEMPLATE_MAP` 中 **「翻译/ASR」→ `audio-recognition`**（原为 `translation`）。
- `getTemplateMeta`（或等价调用链）：若 id 为 `translation`，**返回** `audio-recognition` 的 meta，保证历史记录阶段条仍能渲染。

### 4.3 测试与验收

- 新任务选择模版「识别」或场景「翻译/ASR」：请求中带 `template=audio-recognition`，报告前 JSON 块 `template` 为 `audio-recognition`，`phases` 为五步。
- 打开一条历史记录其 `template_data.template` 为 `translation`：前端仍显示正确 label/phases（与 `audio-recognition` 一致）。
- 单元测试：若有断言写死 `translation` 模版列表，改为仅 `audio-recognition` 或增加映射预期。

## 5. 可选后续（本 spec 不强制）

`_build_template_prompt` 中 `asr_field` / `asr_hint` 当前未按 `meta["asr_records"]` 拼接 `_ASR_RECORDS_HINT`，与 `_ASR_RECORDS_HINT` 定义脱节。可在实现计划中增一项：当 `asr_records` 为真时，将示例 JSON 字段与 hint  append 到提示词，使模型输出与后端解析更一致。

## 6. 决议摘要

| 项 | 决议 |
|----|------|
| 保留的 template id | `audio-recognition` |
| 删除的 template id | `translation` |
| 展示 label | 识别 |
| phases | 选择设备 → 选择语言 → 点击开始 → 开始识别 → 识别结束 |
| 旧数据 | `translation` 映射为 `audio-recognition` 展示与逻辑 |

## 7. 自检

- 无 TBD：标签、阶段、兼容策略已写死。
- 与对话结论一致：用户选 B + 阶段方案 1；标签采用 B 中「识别」。
- 范围限定在 web-diagnostic 模版与映射；不扩展其他模版。
