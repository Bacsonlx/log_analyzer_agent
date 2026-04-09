import './style.css';

import { createStore } from './core/store.js';
import { WsClient } from './core/ws.js';
import { Header } from './components/header.js';
import { HistoryList } from './components/history-list.js';
import { IdleView } from './views/idle.js';
import { AnalyzingView } from './views/analyzing.js';
import { ResultView, getKbModal } from './views/result.js';
import { formatToolName, timestamp, safeFetchJson } from './utils/helpers.js';

let pendingOAuthBridge = '';

(function initUrlParams() {
  const p = new URLSearchParams(location.search);
  pendingOAuthBridge = p.get('oauth_bridge') || '';
  const oe = p.get('oauth_error');
  if (oe) {
    try {
      alert(decodeURIComponent(oe.replace(/\+/g, ' ')));
    } catch {
      alert(oe);
    }
  }
  if (pendingOAuthBridge || oe) {
    const u = new URL(location.href);
    u.searchParams.delete('oauth_bridge');
    u.searchParams.delete('oauth_error');
    const q = u.searchParams.toString();
    history.replaceState(null, '', u.pathname + (q ? `?${q}` : '') + u.hash);
  }
})();

const store = createStore();
store.diag = {};

const ws = new WsClient(store);
store.set('wsClient', ws);

const app = document.getElementById('app');
if (!app) {
  throw new Error('#app missing');
}
app.className =
  'flex flex-col h-full min-h-0 overflow-hidden bg-bg-dark text-slate-100 font-display';
app.innerHTML = `
  <div data-header-mount class="flex-shrink-0"></div>
  <div data-view-shell class="flex-1 min-h-0 flex flex-col overflow-hidden"></div>
  <footer class="flex-shrink-0 border-t border-primary/20 bg-bg-dark px-6 py-1.5 flex flex-wrap justify-between items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-primary/30">
    <span>AIVoice AI Diagnostic</span>
    <div class="flex flex-wrap items-center gap-3 text-primary/25">
      <span>Powered by 敖丙</span>
      <a href="mailto:aobing.hu@tuya.com" class="hover:text-primary/55 transition-colors normal-case">Contact</a>
    </div>
  </footer>
`;

new Header(app.querySelector('[data-header-mount]'), store).mount();

const viewShell = app.querySelector('[data-view-shell]');
let currentView = null;
let mountedViewName = null;

/**
 * 销毁当前视图、挂载新视图并加上入场动画 class
 */
function switchView(name) {
  if (mountedViewName === name && currentView && name !== 'result') {
    return;
  }
  currentView?.destroy();
  currentView = null;
  mountedViewName = null;
  viewShell.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'flex-1 min-h-0 flex flex-col view-enter';
  viewShell.appendChild(el);

  if (name === 'idle') {
    currentView = new IdleView(el, store);
  } else if (name === 'analyzing') {
    currentView = new AnalyzingView(el, store);
  } else if (name === 'result') {
    currentView = new ResultView(el, store);
  }
  currentView?.mount();
  mountedViewName = name;

  if (name === 'idle') {
    HistoryList.loadHistory(store);
  }
}

store.on('view', (v) => {
  if (v) {
    switchView(v);
  }
});

function getTerm() {
  return store.diag?.terminal || null;
}

function addStep(name) {
  const steps = [...(store.get('steps') || [])];
  steps.push({ name, status: 'active' });
  store.set('steps', steps);
}

function completeLastStep() {
  const steps = [...(store.get('steps') || [])];
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i].status === 'active') {
      steps[i] = { ...steps[i], status: 'done' };
      store.set('steps', steps);
      return;
    }
  }
}

function bumpProgressFromSteps() {
  const steps = store.get('steps') || [];
  const doneCount = steps.filter((s) => s.status === 'done').length;
  const total = Math.max(steps.length, doneCount + 2);
  store.set('progress', Math.min(Math.round((doneCount / total) * 90), 90));
}

async function refreshHistory() {
  try {
    const data = await safeFetchJson('/api/history?limit=20');
    store.set('taskHistory', data.history || []);
  } catch (e) {
    console.error('refreshHistory failed', e);
  }
}

async function tryClaimOAuthBridge() {
  const b = pendingOAuthBridge;
  if (!b) {
    return;
  }
  const wid = store.get('webSessionId');
  if (!wid) {
    return;
  }
  pendingOAuthBridge = '';
  try {
    const data = await safeFetchJson('/api/sso-bridge-claim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bridge_token: b, web_session_id: wid }),
    });
    if (data.ok) {
      store.set('ssoVerified', true);
      store.set('ssoWarning', '');
    } else {
      alert(data.error || '领取登录态失败');
    }
  } catch (e) {
    alert(`领取失败: ${e.message}`);
  }
}

async function refreshOAuthEnabled() {
  try {
    const data = await safeFetchJson('/api/oauth/app-log/status');
    store.set('oauthEnabled', !!data.enabled);
  } catch {
    store.set('oauthEnabled', false);
  }
}

store.on('taskAction', (act) => {
  if (!act || !act.type) {
    return;
  }
  if (act.type === 'removeTask') {
    const q = [...(store.get('taskQueue') || [])];
    const t = q.find((x) => x.id === act.taskId);
    if (t?.serverTaskId && ws.isOpen) {
      ws.send({ action: 'stop', task_id: t.serverTaskId });
    }
    store.set(
      'taskQueue',
      q.filter((x) => x.id !== act.taskId),
    );
  } else if (act.type === 'stopAnalysis') {
    const tid = store.get('activeServerTaskId');
    if (tid && ws.isOpen) {
      ws.send({ action: 'stop', task_id: tid });
    }
    const q = (store.get('taskQueue') || []).map((t) =>
      t.status === 'running' ? { ...t, status: 'stopped' } : t,
    );
    store.set('taskQueue', q);
    store.set('activeServerTaskId', '');
    getTerm()?.termLog('SYSTEM', '用户已请求终止任务');
    setTimeout(() => store.set('view', 'idle'), 800);
  }
  store.set('taskAction', null);
});

const kbModal = getKbModal(store);
document.addEventListener('web-diag:open-kb', () => kbModal.open());

ws.onMessage('hello', async (msg) => {
  store.set('webSessionId', msg.web_session_id || '');
  store.set('ssoVerified', false);
  store.set('ssoWarning', '');
  store.set('needSsoHint', null);
  await refreshOAuthEnabled();
  await tryClaimOAuthBridge();
});

ws.onMessage('need_sso', (msg) => {
  const tid = msg.task_id || '';
  if (tid) {
    const q = store.get('taskQueue') || [];
    const hit = q.find((x) => x.serverTaskId === tid);
    if (hit) {
      store.set(
        'taskQueue',
        q.filter((x) => x.id !== hit.id),
      );
    }
  }
  const hint =
    msg.hint ||
    msg.content ||
    '自动下载需要先完成日志平台登录态验证。';
  store.set('ssoWarning', hint);
  store.set('needSsoHint', hint);
});

ws.onMessage('sso_ok', () => {
  store.set('ssoVerified', true);
  store.set('ssoWarning', '');
  store.set('needSsoHint', null);
});

ws.onMessage('queued', (msg) => {
  const tid = msg.task_id;
  const pos = msg.position || 1;
  const q = [...(store.get('taskQueue') || [])];
  const pending = q.find((t) => t.status === 'queued' && !t.serverTaskId);
  if (pending) {
    pending.serverTaskId = tid;
    if (pos > 1) {
      pending.status = 'waiting';
    }
  }
  store.set('taskQueue', q);
  if (pos > 1) {
    getTerm()?.termLog('SYSTEM', `任务已排队，当前位置: 第 ${pos} 位`);
  }
});

ws.onMessage('task_started', (msg) => {
  const tid = msg.task_id;
  const q = [...(store.get('taskQueue') || [])];
  const task =
    q.find((t) => t.serverTaskId === tid) ||
    q.find((t) => t.status === 'queued' || t.status === 'waiting');
  const next = task
    ? q.map((t) =>
        t.id === task.id ? { ...t, status: 'running', startTime: Date.now() } : t,
      )
    : q;
  store.set('taskQueue', next);
  store.set('activeServerTaskId', tid);
  const t0 = task || { message: '', fileName: '' };
  store.set('activeTaskTitle', t0.message || '');
  store.set('activeTaskFile', t0.fileName || '');
  store.set('eventCount', 0);
  store.set('steps', []);
  store.set('assistantText', '');
  store.set('progress', 0);
  store.set('analysisStartTime', Date.now());
  store.set('view', 'analyzing');
  queueMicrotask(() => {
    const term = getTerm();
    term?.clear();
    term?.termLog('SYSTEM', '诊断请求已发送，等待 AI 响应…');
    if ((store.get('taskQueue') || []).length > 1) {
      term?.termLog('SYSTEM', '队列中有多项任务，当前任务已开始执行。');
    }
  });
});

ws.onMessage('tool_use', (msg) => {
  store.set('eventCount', (store.get('eventCount') || 0) + 1);
  const n = formatToolName(msg.tool_name || '');
  addStep(n);
  bumpProgressFromSteps();
  getTerm()?.termLog('TOOL', `调用 ${n}…`);
});

ws.onMessage('tool_result', (msg) => {
  store.set('eventCount', (store.get('eventCount') || 0) + 1);
  completeLastStep();
  bumpProgressFromSteps();
  const preview = (msg.content || '').slice(0, 120).replace(/\n/g, ' ');
  if (preview) {
    getTerm()?.termLog('DATA', preview);
  }
});

ws.onMessage('text', (msg) => {
  const chunk = msg.content || '';
  const prev = store.get('assistantText') || '';
  store.set('assistantText', prev + chunk);
  store.set('eventCount', (store.get('eventCount') || 0) + 1);
  chunk
    .split('\n')
    .filter((l) => l.trim())
    .forEach((l) => getTerm()?.termLog('AI', l.slice(0, 200)));
});

ws.onMessage('result', (msg) => {
  const finalText = msg.final_text || store.get('assistantText') || '';
  const q = [...(store.get('taskQueue') || [])];
  const running = q.find((t) => t.status === 'running');
  const next = running ? q.filter((t) => t.id !== running.id) : q;
  store.set('taskQueue', next);
  store.set('activeServerTaskId', '');
  store.set('progress', 100);
  completeLastStep();
  store.diag?.analyzingView?.stopTimer?.();
  getTerm()?.termLog(
    'DONE',
    `诊断完成 (${((msg.duration_ms || 0) / 1000).toFixed(1)}s)`,
  );
  store.set('currentResultMd', finalText);
  store.set('currentResultName', `诊断报告_${timestamp()}`);
  store.set('resultFromLive', true);
  store.set('resultMeta', {
    status: 'success',
    duration_ms: msg.duration_ms || 0,
    cost_usd: msg.cost_usd || 0,
    template_data: msg.template_data || null,
    extracted_files: msg.extracted_files || [],
  });
  refreshHistory();
  setTimeout(() => store.set('view', 'result'), 400);
});

ws.onMessage('error', (msg) => {
  getTerm()?.termLog('ERROR', msg.content || '未知错误');
  store.diag?.analyzingView?.stopTimer?.();
  const q = (store.get('taskQueue') || []).map((t) =>
    t.status === 'running' ? { ...t, status: 'error' } : t,
  );
  store.set('taskQueue', q);
  setTimeout(() => {
    store.set('view', 'idle');
    store.set('ssoWarning', '');
  }, 2000);
});

ws.onMessage('stopped', () => {
  getTerm()?.termLog('SYSTEM', '任务已被终止');
});

ws.onMessage('history_file', (msg) => {
  if (msg.file) {
    store.set('currentHistoryFile', msg.file);
  }
});

ws.onMessage('knowledge_progress', (msg) =>
  store.set('knowledge_progress', { ...msg, _ts: Date.now() }),
);
ws.onMessage('knowledge_result', (msg) =>
  store.set('knowledge_result', { ...msg, _ts: Date.now() }),
);

ws.connect();

switchView(store.get('view'));

const reportFile = new URLSearchParams(location.search).get('report');
if (reportFile) {
  history.replaceState(null, '', location.pathname);
  setTimeout(async () => {
    try {
      const data = await safeFetchJson(
        `/api/history/${encodeURIComponent(reportFile)}`,
      );
      if (data.error) {
        alert(data.error);
        return;
      }
      const safeName = (data.name || '').replace(/[/\\:*?"<>|]/g, '_');
      store.set('currentHistoryFile', reportFile);
      store.set('currentResultMd', data.result || '');
      store.set('currentResultName', safeName);
      store.set('resultFromLive', false);
      store.set('resultMeta', {
        duration_ms: data.duration_ms || 0,
        cost_usd: data.cost_usd || 0,
        tool_count: data.tool_count || 0,
        score: data.score,
        has_failure: data.has_failure,
        template_data: data.template_data || null,
        extracted_files: data.extracted_files || [],
      });
      store.set('view', 'result');
    } catch (e) {
      alert(`加载失败: ${e.message}`);
    }
  }, 300);
}
