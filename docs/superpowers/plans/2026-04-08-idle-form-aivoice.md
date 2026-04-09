# Idle 首页表单 AIVoice 精简 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精简首页诊断表单：去除问题描述必填、场景列表只保留5个AIVoice场景、选场景后模版自动联动。

**Architecture:** 所有改动集中在 `idle.js` 一个文件。修改常量定义、校验逻辑、新增联动方法并在 `onMount()` 中绑定事件。无新文件。

**Tech Stack:** Vanilla JS, Vite (build only), Tailwind CSS

---

## File Map

| 文件 | 操作 | 说明 |
|------|------|------|
| `web-diagnostic/frontend/src/views/idle.js` | Modify | 全部改动所在 |

---

### Task 1: 精简场景列表 + 添加联动映射常量

**Files:**
- Modify: `web-diagnostic/frontend/src/views/idle.js:9-21`

- [ ] **Step 1: 替换 `SCENARIO_OPTIONS` 并新增 `SCENARIO_TEMPLATE_MAP`**

将文件顶部的 `SCENARIO_OPTIONS` 从 11 项精简为 5 项，并在其后新增映射表：

```js
const SCENARIO_OPTIONS = [
  '录音问题',
  '翻译/ASR',
  '云同步上传',
  '离线文件传输',
  '转写/总结',
];

const SCENARIO_TEMPLATE_MAP = {
  '录音问题': 'recording',
  '翻译/ASR': 'translation',
  '云同步上传': 'cloud-upload',
  '离线文件传输': 'offline-transcription',
  '转写/总结': 'offline-transcription',
};
```

- [ ] **Step 2: 验证场景下拉框已精简**

```bash
cd web-diagnostic/frontend && npm run build 2>&1 | tail -5
```

Expected: `✓ built in` — 无报错。

- [ ] **Step 3: Commit**

```bash
git add web-diagnostic/frontend/src/views/idle.js
git commit -m "feat: reduce scenario options to 5 AIVoice scenarios and add template map"
```

---

### Task 2: 移除问题描述必填校验

**Files:**
- Modify: `web-diagnostic/frontend/src/views/idle.js` → `_syncStartDisabled()` 和 `startAnalysis()`

- [ ] **Step 1: 修改 `_syncStartDisabled()`**

找到方法（约第 371 行），将原逻辑：

```js
let ok = false;
if (logMode === 'auto') {
  ok = !!(problem && hasInfo && ssoOkForAuto && wsOk);
} else {
  ok = !!(problem || hasFile) && wsOk;
}
```

改为：

```js
let ok = false;
if (logMode === 'auto') {
  ok = !!(hasInfo && ssoOkForAuto && wsOk);
} else {
  ok = !!(hasFile && wsOk);
}
```

同时删除此方法开头对 `problem` 的赋值（第 374 行）：

```js
// 删除这行：
const problem = this.$('[data-problem]')?.value?.trim() || '';
```

- [ ] **Step 2: 修改 `startAnalysis()` 中 manual 模式守卫**

找到方法（约第 497 行），将：

```js
if (logMode === 'manual' && !problem && !this.store.get('uploadedFilePath')) {
  return;
}
```

改为：

```js
if (logMode === 'manual' && !this.store.get('uploadedFilePath')) {
  return;
}
```

- [ ] **Step 3: 同步移除 `onMount()` 中对 `[data-problem]` 的 input 监听**

找到 `onMount()` 中的 inputs 数组（约第 238 行），将 `'[data-problem]'` 从数组中移除：

```js
const inputs = [
  '[data-field-socrates]',
  '[data-field-ticket]',
  '[data-field-account]',
  '[data-field-uid]',
];
```

- [ ] **Step 4: 构建验证**

```bash
cd web-diagnostic/frontend && npm run build 2>&1 | tail -5
```

Expected: `✓ built in` — 无报错。

- [ ] **Step 5: Commit**

```bash
git add web-diagnostic/frontend/src/views/idle.js
git commit -m "feat: make problem description optional, remove from start validation"
```

---

### Task 3: 实现场景→模版联动

**Files:**
- Modify: `web-diagnostic/frontend/src/views/idle.js` → 新增方法 `_syncTemplateFromScenario()`，修改 `onMount()`

- [ ] **Step 1: 新增 `_syncTemplateFromScenario()` 方法**

在 `_syncStartDisabled()` 方法之前插入：

```js
_syncTemplateFromScenario() {
  const scenario = this.$('[data-scenario]')?.value || '';
  const templateId = SCENARIO_TEMPLATE_MAP[scenario];
  if (!templateId) return;
  const tmplEl = this.$('[data-template]');
  if (tmplEl) tmplEl.value = templateId;
}
```

- [ ] **Step 2: 在 `onMount()` 中绑定场景 change 事件并做初始同步**

找到 `onMount()` 中现有的场景监听（约第 252 行）：

```js
this.$('[data-scenario]')?.addEventListener('change', () =>
  this._syncStartDisabled(),
);
```

替换为：

```js
this.$('[data-scenario]')?.addEventListener('change', () => {
  this._syncTemplateFromScenario();
  this._syncStartDisabled();
});
```

在 `_syncStartDisabled()` 初始调用（`onMount()` 末尾）之前插入初始联动调用：

```js
this._syncTemplateFromScenario();
this._syncStartDisabled();
```

（原来末尾只有 `this._syncStartDisabled()`，改为上面两行）

- [ ] **Step 3: 构建验证**

```bash
cd web-diagnostic/frontend && npm run build 2>&1 | tail -5
```

Expected: `✓ built in` — 无报错。

- [ ] **Step 4: 手动验证联动行为**

启动开发服务器：
```bash
cd web-diagnostic/frontend && npm run dev
```

访问 `http://localhost:5173`，验证：
1. 页面加载时，场景默认选中「录音问题」，模版自动显示「录音问题」（`recording`）
2. 切换场景到「翻译/ASR」，模版自动变为「翻译/ASR」（`translation`）
3. 切换到「转写/总结」，模版自动变为「离线转写/总结」（`offline-transcription`）
4. 手动修改模版下拉框后，值被覆盖（用户可覆盖）
5. manual 模式下，未填问题描述、只上传文件，「启动诊断」按钮可用

- [ ] **Step 5: 构建 production bundle**

```bash
cd web-diagnostic/frontend && npm run build
```

Expected: `✓ built in` — 无报错，`dist/` 已更新。

- [ ] **Step 6: Commit**

```bash
git add web-diagnostic/frontend/src/views/idle.js
git commit -m "feat: sync report template automatically when scenario changes"
```
