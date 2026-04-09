# Idle 首页表单精简 & AIVoice 场景联动

**Date:** 2026-04-08  
**Scope:** `web-diagnostic/frontend/src/views/idle.js`, `frontend/src/templates/index.js`

---

## 背景

首页诊断表单当前面向多场景（BLE配网、MQTT等），但实际使用场景收窄至 AIVoice。需要：

1. 去除问题描述的必填校验
2. 场景列表只保留 AIVoice 相关的 5 个
3. 选择场景后报告模版自动联动更新（用户仍可手动覆盖）

---

## 变更说明

### 1. 问题描述非必填

文件：`idle.js` → `_syncStartDisabled()`

| 模式 | 原启动条件 | 新启动条件 |
|------|-----------|-----------|
| auto | `problem && hasInfo && ssoOk && wsOk` | `hasInfo && ssoOk && wsOk` |
| manual | `(problem \|\| hasFile) && wsOk` | `hasFile && wsOk` |

同步调整 `startAnalysis()` 中 manual 模式的守卫：去掉 `!problem` 条件，只检查 `!filePath`。

### 2. 场景列表精简

文件：`idle.js` → `SCENARIO_OPTIONS`

保留（5 项）：
```
录音问题 / 翻译/ASR / 云同步上传 / 离线文件传输 / 转写/总结
```

移除：自动识别、BLE配网、MQTT通信、OTA升级、设备控制、网络连接。

### 3. 场景→模版联动

文件：`idle.js`

新增映射常量：

```js
const SCENARIO_TEMPLATE_MAP = {
  '录音问题': 'recording',
  '翻译/ASR': 'translation',
  '云同步上传': 'cloud-upload',
  '离线文件传输': 'offline-transcription',
  '转写/总结': 'offline-transcription',
};
```

新增方法 `_syncTemplateFromScenario()`：
- 读取 `[data-scenario]` 当前值
- 查表得到 template id，更新 `[data-template]` 的 `value`
- 若场景无映射（未来扩展），模版保持当前值不变

调用时机：
- `onMount()` 监听 `[data-scenario]` 的 `change` 事件 → 调用此方法
- `onMount()` 末尾调用一次，确保初始同步

---

## 不变的部分

- 模版下拉框继续显示，用户选场景后可手动覆盖
- `templates/index.js` 的 5 个模版定义不变
- 其余字段（用户信息、日志来源、SSO）逻辑不变
