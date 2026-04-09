import { Component } from '../core/component.js';
import { SsoPanel } from '../components/sso-panel.js';
import { FileUpload } from '../components/file-upload.js';
import { TaskQueue } from '../components/task-queue.js';
import { HistoryList } from '../components/history-list.js';
import { esc, safeFetchJson } from '../utils/helpers.js';
import { TEMPLATES } from '../templates/index.js';

const SCENARIO_OPTIONS = [
  '录音问题',
  '实时链路',
  '云同步上传',
  '离线文件传输',
  '转写/总结',
];

const SCENARIO_TEMPLATE_MAP = {
  '录音问题': 'recording',
  '实时链路': 'audio-recognition',
  '云同步上传': 'cloud-upload',
  '离线文件传输': 'offline-transcription',
  '转写/总结': 'offline-transcription',
};

/**
 * 首页：双栏布局、SSO、日志来源、上传、场景与启动诊断
 */
export class IdleView extends Component {
  constructor(container, store) {
    super(container, store);
    this._ssoPanel = null;
    this._fileUpload = null;
    this._taskQueue = null;
    this._historyList = null;
  }

  render() {
    const scenarioOpts = SCENARIO_OPTIONS.map(
      (label) => `<option value="${esc(label)}">${esc(label)}</option>`,
    ).join('');
    const templateOpts = [
      '<option value="auto">自动（由AI判断）</option>',
      ...Object.entries(TEMPLATES).map(
        ([id, t]) => `<option value="${esc(id)}">${esc(t.label)}</option>`,
      ),
    ].join('');

    return `
<div class="h-full min-h-0 overflow-y-auto cyber-grid">
  <div class="max-w-[1400px] mx-auto px-4 py-6">
    <div
      class="grid grid-cols-1 xl:grid-cols-5 gap-6"
      data-idle-grid
    >
      <div
        id="idleMainColumn"
        class="idleMainColumn space-y-5 xl:col-span-5 transition-[grid-column] duration-300"
        data-idle-main
      >
        <h2 class="text-lg font-bold text-slate-100 tracking-wide flex items-center gap-2">
          <span class="material-symbols-outlined text-primary">add_task</span>
          新建诊断任务
        </h2>

        <div data-sso-banner-wrap></div>

        <div data-sso-panel-host></div>

        <div
          id="userInfoPanel"
          class="rounded-xl border border-primary/20 bg-surface/80 p-4 space-y-3 neon-border hidden"
          data-user-info
        >
          <span class="text-[10px] uppercase tracking-widest text-primary/60 font-bold">用户信息</span>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">Socrates工单号</label>
              <div class="flex gap-2">
                <input
                  type="text"
                  data-field-socrates
                  class="flex-1 text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 focus:border-primary/50 focus:ring-0"
                  placeholder="工单 ID 或链接"
                />
                <button
                  type="button"
                  data-fetch-ticket
                  class="shrink-0 px-3 py-2 rounded-lg bg-primary/15 border border-primary/35 text-primary text-[10px] font-bold uppercase tracking-wider hover:bg-primary/25 transition-colors disabled:opacity-40"
                >
                  <span class="material-symbols-outlined text-xs align-middle">sync</span>
                  获取
                </button>
              </div>
              <p data-ticket-status class="hidden text-[10px] mt-1"></p>
            </div>
            <div>
              <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">App Ticket ID</label>
              <input
                type="text"
                data-field-ticket
                class="w-full text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 focus:border-primary/50 focus:ring-0"
                placeholder="可选"
              />
            </div>
            <div>
              <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">账号</label>
              <input
                type="text"
                data-field-account
                class="w-full text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 focus:border-primary/50 focus:ring-0"
              />
            </div>
            <div>
              <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">UID</label>
              <input
                type="text"
                data-field-uid
                class="w-full text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 focus:border-primary/50 focus:ring-0"
              />
            </div>
          </div>
        </div>

        <div>
          <span class="block text-[10px] text-primary/50 uppercase tracking-widest mb-2">日志来源</span>
          <div class="flex flex-wrap gap-2">
            <button type="button" data-log-mode="auto" class="log-mode-btn px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all">
              自动下载
            </button>
            <button type="button" data-log-mode="manual" class="log-mode-btn px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all">
              手动上传
            </button>
          </div>
        </div>

        <div data-file-upload-host class="hidden"></div>

        <div
          id="logAuto"
          class="rounded-lg border border-primary/15 bg-primary/5 px-4 py-3 text-xs text-slate-400 hidden"
          data-log-auto-info
        >
          <span class="material-symbols-outlined text-primary text-sm align-middle mr-1">cloud_download</span>
          将按 UID / 账号在日志平台检索并下载日志；需先完成上方登录态校验。
        </div>

        <div data-problem-section>
          <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">问题描述</label>
          <textarea
            data-problem
            rows="4"
            class="w-full text-sm bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-600 focus:border-primary/50 focus:ring-0 resize-y"
            placeholder="现象、复现步骤、期望行为…"
          ></textarea>
        </div>

        <div data-scenario-section>
          <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">诊断场景</label>
          <select
            data-scenario
            class="w-full text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 focus:border-primary/50 focus:ring-0"
          >
            ${scenarioOpts}
          </select>
        </div>

        <div data-template-section>
          <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">报告模版</label>
          <select
            data-template
            class="w-full text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 focus:border-primary/50 focus:ring-0"
          >
            ${templateOpts}
          </select>
        </div>

        <button
          type="button"
          data-start-analysis
          class="w-full bg-primary text-bg-dark py-2.5 rounded-lg font-bold text-xs uppercase tracking-widest hover:brightness-110 transition-all flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed neon-border"
          disabled
        >
          <span class="material-symbols-outlined text-lg">play_arrow</span>
          启动诊断
        </button>
      </div>

      <aside
        id="idleSidebar"
        class="idleSidebar hidden xl:col-span-2 space-y-4"
        data-idle-sidebar
      >
        <div data-task-queue-host></div>
        <div data-history-host></div>
      </aside>
    </div>
  </div>
</div>`;
  }

  onMount() {
    const ssoHost = this.$('[data-sso-panel-host]');
    if (ssoHost) {
      this._ssoPanel = new SsoPanel(ssoHost, this.store);
      this._ssoPanel.mount();
    }

    const fuHost = this.$('[data-file-upload-host]');
    if (fuHost) {
      this._fileUpload = new FileUpload(fuHost, this.store);
      this._fileUpload.mount();
    }

    const tqHost = this.$('[data-task-queue-host]');
    if (tqHost) {
      this._taskQueue = new TaskQueue(tqHost, this.store);
      this._taskQueue.mount();
    }

    const hiHost = this.$('[data-history-host]');
    if (hiHost) {
      this._historyList = new HistoryList(hiHost, this.store);
      this._historyList.mount();
    }

    this._bindModeButtons();
    this._syncLogModeButtons();
    this._applyLayoutGate();

    this.on('[data-fetch-ticket]', 'click', () => this._fetchTicket());
    this.on('[data-field-socrates]', 'keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this._fetchTicket();
      }
    });

    this.on('[data-start-analysis]', 'click', () => this.startAnalysis());

    const inputs = [
      '[data-field-socrates]',
      '[data-field-ticket]',
      '[data-field-account]',
      '[data-field-uid]',
    ];
    inputs.forEach((sel) => {
      const el = this.$(sel);
      if (el) {
        el.addEventListener('input', () => this._syncStartDisabled());
        el.addEventListener('change', () => this._syncStartDisabled());
      }
    });
    this.$('[data-scenario]')?.addEventListener('change', () => {
      this._syncTemplateFromScenario();
      this._syncStartDisabled();
    });

    this.subscribe('ssoWarning', () => this._syncSsoBanner());
    this.subscribe('ssoVerified', () => {
      this._applyLayoutGate();
      this._syncSsoBanner();
      this._syncStartDisabled();
    });
    this.subscribe('logMode', () => {
      this._syncLogModeButtons();
      this._applyLayoutGate();
      this._syncStartDisabled();
    });
    this.subscribe('wsState', () => this._syncStartDisabled());
    this.subscribe('uploadedFilePath', () => this._syncStartDisabled());
    this.subscribe('needSsoHint', (hint) => {
      if (!hint || !this._ssoPanel) return;
      const text =
        typeof hint === 'string' ? hint : hint.hint || hint.message || '';
      if (!text) return;
      this._ssoPanel.showNeedSsoHint(text);
      this.store.set('needSsoHint', '');
    });

    this._syncSsoBanner();
    this._syncTemplateFromScenario();
    this._syncStartDisabled();
  }

  _syncSsoBanner() {
    const wrap = this.$('[data-sso-banner-wrap]');
    if (!wrap) return;
    const text = (this.store.get('ssoWarning') || '').trim();
    if (!text) {
      wrap.innerHTML = '';
      return;
    }
    wrap.innerHTML = `<div class="rounded-lg border border-accent-yellow/35 bg-accent-yellow/10 px-3 py-2 text-[11px] text-accent-yellow/95">${esc(text)}</div>`;
  }

  _bindModeButtons() {
    this.$$('.log-mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const mode = btn.getAttribute('data-log-mode');
        if (mode === 'auto' || mode === 'manual') {
          this.store.set('logMode', mode);
        }
      });
    });
  }

  _syncLogModeButtons() {
    const mode = this.store.get('logMode') || 'auto';
    const active =
      'px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all bg-primary text-bg-dark';
    const inactive =
      'px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all text-slate-500 hover:text-slate-300';
    this.$$('.log-mode-btn').forEach((btn) => {
      const m = btn.getAttribute('data-log-mode');
      btn.className = m === mode ? active : inactive;
    });
  }

  _applyLayoutGate() {
    const sso = !!this.store.get('ssoVerified');
    const logMode = this.store.get('logMode') || 'auto';
    const sidebar = this.$('[data-idle-sidebar]');
    const main = this.$('[data-idle-main]');
    const userInfo = this.$('[data-user-info]');
    const fileHost = this.$('[data-file-upload-host]');
    const logAuto = this.$('[data-log-auto-info]');

    if (sidebar) {
      sidebar.classList.toggle('hidden', !sso);
      sidebar.classList.toggle('xl:block', sso);
    }
    if (main) {
      main.classList.toggle('xl:col-span-3', sso);
      main.classList.toggle('xl:col-span-5', !sso);
    }

    const scenSec = this.$('[data-scenario-section]');
    const tmplSec = this.$('[data-template-section]');

    if (!sso && logMode === 'auto') {
      userInfo?.classList.add('hidden');
      fileHost?.classList.add('hidden');
      logAuto?.classList.add('hidden');
      this.$('[data-problem-section]')?.classList.add('hidden');
      scenSec?.classList.add('hidden');
      tmplSec?.classList.add('hidden');
    } else if (!sso && logMode === 'manual') {
      userInfo?.classList.add('hidden');
      fileHost?.classList.remove('hidden');
      logAuto?.classList.add('hidden');
      this.$('[data-problem-section]')?.classList.remove('hidden');
      scenSec?.classList.remove('hidden');
      tmplSec?.classList.remove('hidden');
    } else {
      this.$('[data-problem-section]')?.classList.remove('hidden');
      scenSec?.classList.remove('hidden');
      tmplSec?.classList.remove('hidden');
      userInfo?.classList.toggle('hidden', logMode === 'manual');
      fileHost?.classList.toggle('hidden', logMode !== 'manual');
      logAuto?.classList.toggle('hidden', logMode !== 'auto');
    }
  }

  _hasUserInfo() {
    const s = (sel) => this.$(sel)?.value?.trim() || '';
    return !!(
      s('[data-field-socrates]') ||
      s('[data-field-ticket]') ||
      s('[data-field-account]') ||
      s('[data-field-uid]')
    );
  }

  _syncTemplateFromScenario() {
    const scenario = this.$('[data-scenario]')?.value || '';
    const templateId = SCENARIO_TEMPLATE_MAP[scenario];
    if (!templateId) return;
    const tmplEl = this.$('[data-template]');
    if (tmplEl) tmplEl.value = templateId;
  }

  _syncStartDisabled() {
    const btn = this.$('[data-start-analysis]');
    if (!btn) return;
    const hasFile = !!(this.store.get('uploadedFilePath') || '').trim();
    const hasInfo = this._hasUserInfo();
    const ws = this.store.get('wsClient');
    const wsOk =
      this.store.get('wsState') === 'connected' && !!ws?.isOpen;
    const logMode = this.store.get('logMode') || 'auto';
    const ssoOkForAuto = logMode !== 'auto' || !!this.store.get('ssoVerified');

    let ok = false;
    if (logMode === 'auto') {
      ok = !!(hasInfo && ssoOkForAuto && wsOk);
    } else {
      ok = !!(hasFile && wsOk);
    }
    btn.disabled = !ok;
  }

  async _fetchTicket() {
    const input = this.$('[data-field-socrates]');
    const btn = this.$('[data-fetch-ticket]');
    const statusEl = this.$('[data-ticket-status]');
    let rawValue = input?.value?.trim() || '';
    if (!rawValue) {
      this._ticketStatus('请输入工单 ID', 'text-accent-red');
      return;
    }
    const idMatch = rawValue.match(/[?&]id=(\d+)/);
    const ticketId = idMatch ? idMatch[1] : rawValue.replace(/\D/g, '');
    if (!ticketId) {
      this._ticketStatus('无法识别工单 ID', 'text-accent-red');
      return;
    }
    if (input) input.value = ticketId;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML =
        '<span class="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin inline-block"></span>';
    }
    this._ticketStatus('正在获取工单信息…', 'text-primary/60');

    try {
      const hdrs = { Accept: 'application/json' };
      const sid = this.store.get('webSessionId') || '';
      if (sid) hdrs['X-Web-Diagnostic-Session'] = sid;
      const data = await safeFetchJson(
        `/api/fetch-ticket?ticket_id=${encodeURIComponent(ticketId)}`,
        { headers: hdrs },
      );
      if (data.error) {
        this._ticketStatus(data.error, 'text-accent-red');
        return;
      }
      const p = data.params || {};
      const accountEl = this.$('[data-field-account]');
      const uidEl = this.$('[data-field-uid]');
      if (p.account && accountEl) accountEl.value = p.account;
      if (p.uid && uidEl) uidEl.value = p.uid;
      const problemEl = this.$('[data-problem]');
      if (data.title && problemEl && !problemEl.value.trim()) {
        let desc = `[工单#${ticketId}] ${data.title}`;
        if (data.problem_text) {
          const lines = data.problem_text
            .split('\n')
            .filter(
              (l) =>
                l.trim() &&
                !/^\d+、/.test(l) &&
                !l.includes('？'),
            );
          const useful = lines.slice(0, 5).join('\n');
          if (useful) desc += `\n${useful}`;
        }
        problemEl.value = desc;
      }
      const infoItems = [];
      if (data.title) infoItems.push(data.title);
      if (data.customer) infoItems.push(`客户: ${data.customer}`);
      if (p.uid) {
        const src = p.uid_source === 'account_lookup' ? '(自动查询)' : '';
        infoItems.push(`UID: ${p.uid}${src}`);
      }
      if (p.region) infoItems.push(`区域: ${p.region}`);
      if (p.pid) infoItems.push(`PID: ${p.pid}`);
      if (p.platform) infoItems.push(p.platform);
      this._ticketStatus(`已获取: ${infoItems.join(' · ')}`, 'text-neon-green');
      this._syncStartDisabled();
    } catch (e) {
      this._ticketStatus(`请求失败: ${e.message}`, 'text-accent-red');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML =
          '<span class="material-symbols-outlined text-xs align-middle">sync</span> 获取';
      }
    }
  }

  _ticketStatus(text, cls) {
    const el = this.$('[data-ticket-status]');
    if (!el) return;
    el.textContent = text;
    el.className = `text-[10px] mt-1 ${cls}`;
    el.classList.remove('hidden');
  }

  /**
   * 组装消息并通过 wsClient 发送（由 main 注入 store.wsClient）
   */
  startAnalysis() {
    const ws = this.store.get('wsClient');
    if (!ws || !ws.isOpen) return;

    const problem = this.$('[data-problem]')?.value?.trim() || '';
    const scenario = this.$('[data-scenario]')?.value || '';
    const template = this.$('[data-template]')?.value || 'auto';
    const socratesId = this.$('[data-field-socrates]')?.value?.trim() || '';
    const ticketId = this.$('[data-field-ticket]')?.value?.trim() || '';
    const account = this.$('[data-field-account]')?.value?.trim() || '';
    const uid = this.$('[data-field-uid]')?.value?.trim() || '';
    const logMode = this.store.get('logMode') || 'auto';

    if (logMode === 'auto' && !this._hasUserInfo()) return;
    if (logMode === 'manual' && !this.store.get('uploadedFilePath')) {
      return;
    }

    const parts = [];
    if (socratesId) parts.push(`Socrates 工单号: ${socratesId}`);
    if (ticketId) parts.push(`App Ticket ID: ${ticketId}`);
    if (account) parts.push(`账号: ${account}`);
    if (uid) parts.push(`UID: ${uid}`);

    let message = '';
    if (parts.length) message += `用户信息: ${parts.join(', ')}\n`;
    if (scenario) message += `诊断场景: ${scenario}\n`;

    if (logMode === 'auto') {
      message += '请搜索并下载日志，然后进行诊断分析。\n';
      message +=
        '日志搜索优先级：优先使用 UID 搜索（search_logs query_type=uid），如果没有 UID 才使用账号搜索。\n';
    }

    if (problem) {
      message += `问题描述: ${problem}\n`;
    } else {
      message += this.store.get('uploadedFilePath')
        ? '请分析这个日志文件的问题。\n'
        : '请诊断分析。\n';
    }

    let displayName;
    let filePath;
    if (logMode === 'manual') {
      displayName = this.store.get('uploadedFileName') || '无文件';
      filePath = this.store.get('uploadedFilePath') || '';
      if (this.store.get('uploadedFilePath')) {
        message +=
          '请优先分析已上传的日志文件，如需更多信息可结合用户信息搜索补充日志。\n';
      }
    } else {
      displayName = uid || ticketId || account || '自动下载';
      filePath = '';
    }

    const counter = (this.store.get('taskIdCounter') || 0) + 1;
    this.store.set('taskIdCounter', counter);
    const task = {
      id: counter,
      serverTaskId: '',
      message,
      filePath,
      fileName: displayName,
      status: 'queued',
      startTime: null,
      result: null,
    };
    const q = [...(this.store.get('taskQueue') || [])];
    q.push(task);
    this.store.set('taskQueue', q);

    if (!ws.send({ message, file_path: filePath, template })) {
      q.pop();
      this.store.set('taskQueue', [...q]);
      return;
    }

    const prob = this.$('[data-problem]');
    if (prob) prob.value = '';
    if (logMode === 'manual') {
      this.store.set('uploadedFilePath', '');
      this.store.set('uploadedFileName', '');
      this._fileUpload?.update();
    }
    this._syncStartDisabled();
  }

  destroy() {
    this._ssoPanel?.destroy();
    this._ssoPanel = null;
    this._fileUpload?.destroy();
    this._fileUpload = null;
    this._taskQueue?.destroy();
    this._taskQueue = null;
    this._historyList?.destroy();
    this._historyList = null;
    super.destroy();
  }
}
