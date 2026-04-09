import { Component } from '../core/component.js';
import { esc } from '../utils/helpers.js';
import { renderMarkdown, highlightAll } from '../utils/markdown.js';

/**
 * 知识库归纳：右侧抽屉，WebSocket knowledge 流程
 */
export class KbModal extends Component {
  constructor(container, store) {
    super(container, store);
    this._open = false;
    this._step = 1;
    this._logs = [];
    this._resultMd = '';
    this._status = '';
    this._closing = false;
    this._kbStoreBound = false;
  }

  render() {
    const visible = this._open ? '' : 'hidden';
    const panelAnim = this._closing ? 'drawer-leave' : 'drawer-enter';
    return `
<div class="fixed inset-0 z-[200] ${visible}" data-kb-root>
  <div
    class="absolute inset-0 bg-black/70 backdrop-blur-[2px] transition-opacity opacity-100"
    data-kb-backdrop
    aria-hidden="true"
  ></div>
  <aside
    class="absolute right-0 top-0 h-full w-full max-w-lg flex flex-col bg-surface border-l border-primary/25 shadow-[-12px_0_40px_rgba(0,0,0,0.45)] ${this._open && !this._closing ? panelAnim : ''}"
    data-kb-panel
    role="dialog"
    aria-modal="true"
    aria-labelledby="kb-drawer-title"
  >
    <header class="flex items-center justify-between gap-2 px-4 py-3 border-b border-primary/15 bg-bg-dark/80 flex-shrink-0">
      <div class="flex items-center gap-2 min-w-0">
        <span class="material-symbols-outlined text-neon-purple">menu_book</span>
        <h2 id="kb-drawer-title" class="text-sm font-bold text-slate-100 truncate">归纳到知识库</h2>
      </div>
      <button type="button" data-kb-close class="p-1.5 rounded-lg text-slate-400 hover:text-primary hover:bg-primary/10 transition-colors" aria-label="关闭">
        <span class="material-symbols-outlined">close</span>
      </button>
    </header>

    <div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-4" data-kb-body>
      ${this._renderStepContent()}
    </div>

    <footer class="flex-shrink-0 border-t border-primary/15 bg-bg-dark/90 px-4 py-2.5">
      <p class="text-[10px] font-mono text-slate-500 truncate" data-kb-status>${esc(this._status || '就绪')}</p>
    </footer>
  </aside>
</div>`;
  }

  _renderStepContent() {
    if (this._step === 1) {
      return `
<div class="space-y-3">
  <p class="text-xs text-slate-400 leading-relaxed">
    请补充与本次诊断相关的上下文或归纳重点（可选）。提交后将通过当前 WebSocket 会话发送至服务端处理。
  </p>
  <textarea
    data-kb-note
    rows="8"
    class="w-full rounded-lg border border-primary/20 bg-bg-dark px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-primary/40 font-mono"
    placeholder="例如：根因、模块、后续建议…"
  ></textarea>
  <button type="button" data-kb-start class="w-full py-2.5 rounded-lg border border-neon-purple/50 bg-neon-purple/15 text-neon-purple text-xs font-bold uppercase tracking-wider hover:bg-neon-purple/25 transition-colors flex items-center justify-center gap-2">
    <span class="material-symbols-outlined text-base">auto_awesome</span>
    开始归纳
  </button>
</div>`;
    }
    if (this._step === 2) {
      const lines = this._logs
        .map(
          (l) =>
            `<div class="text-[11px] font-mono text-primary/80 border-l-2 border-primary/30 pl-2 py-0.5">${esc(l)}</div>`,
        )
        .join('');
      return `
<div class="space-y-3">
  <div class="flex items-center gap-2 text-primary">
    <span class="material-symbols-outlined animate-spin text-lg">progress_activity</span>
    <span class="text-xs font-bold">正在归纳…</span>
  </div>
  <div class="rounded-lg border border-primary/15 bg-bg-dark/80 p-3 max-h-64 overflow-y-auto space-y-1 font-mono" data-kb-log-box>
    ${lines || '<span class="text-slate-600 text-xs">等待进度…</span>'}
  </div>
</div>`;
    }
    const html = this._resultMd
      ? renderMarkdown(this._resultMd)
      : '<p class="text-slate-500 text-sm">无结果</p>';
    return `
<div class="space-y-3">
  <p class="text-xs text-neon-green font-bold flex items-center gap-1">
    <span class="material-symbols-outlined text-base">check_circle</span>
    归纳结果
  </p>
  <div class="report-content text-sm rounded-lg border border-primary/15 bg-bg-dark/50 p-4" data-kb-result>${html}</div>
  <button type="button" data-kb-reset class="w-full py-2 rounded-lg border border-slate-600 text-slate-300 text-xs font-bold uppercase tracking-wider hover:border-primary/40 transition-colors">
    再次归纳
  </button>
</div>`;
  }

  onMount() {
    this.on('[data-kb-close]', 'click', () => this.close());
    this.on('[data-kb-backdrop]', 'click', () => this.close());
    this.on('[data-kb-start]', 'click', () => this.startSummary());
    this.on('[data-kb-reset]', 'click', () => {
      this._step = 1;
      this._logs = [];
      this._resultMd = '';
      this._status = '就绪';
      this.update();
    });

    if (!this._kbWsSubscribed) {
      this._kbWsSubscribed = true;
      this.subscribe('knowledge_progress', (msg) => {
        if (msg) {
          this.onProgress(msg);
        }
      });
      this.subscribe('knowledge_result', (msg) => {
        if (msg) {
          this.onResult(msg);
        }
      });
    }

    if (this._step === 3 && this._resultMd) {
      const box = this.$('[data-kb-result]');
      if (box) {
        highlightAll(box);
      }
    }
  }

  open() {
    this._open = true;
    this._closing = false;
    if (!(this._step === 3 && this._resultMd)) {
      this._step = 1;
      this._logs = [];
      this._resultMd = '';
    }
    this._status = '就绪';
    this.update();
  }

  close() {
    if (!this._open || this._closing) {
      return;
    }
    this._closing = true;
    const panel = this.$('[data-kb-panel]');
    if (panel) {
      panel.classList.remove('drawer-enter');
      panel.classList.add('drawer-leave');
      let finished = false;
      const done = () => {
        if (finished) {
          return;
        }
        finished = true;
        this._open = false;
        this._closing = false;
        this.update();
      };
      panel.addEventListener('animationend', done, { once: true });
      setTimeout(done, 350);
    } else {
      this._open = false;
      this._closing = false;
      this.update();
    }
  }

  startSummary() {
    const ta = this.$('[data-kb-note]');
    const prompt = (ta?.value || '').trim();
    const ws = this.store.get('wsClient');
    if (!ws?.isOpen) {
      this._status = 'WebSocket 未连接';
      this._syncStatus();
      return;
    }
    const ok = ws.send({
      action: 'knowledge',
      message: prompt,
    });
    if (!ok) {
      this._status = '发送失败';
      this._syncStatus();
      return;
    }
    this._step = 2;
    this._logs = [];
    this._resultMd = '';
    this._status = '已发送归纳请求…';
    this.update();
  }

  /** @param {object} msg WebSocket knowledge_progress */
  onProgress(msg) {
    if (!this._open || this._step !== 2) {
      return;
    }
    const line =
      msg?.content ||
      msg?.message ||
      msg?.line ||
      msg?.text ||
      (typeof msg?.chunk === 'string' ? msg.chunk : '') ||
      JSON.stringify(msg || {});
    this._logs.push(String(line));
    const box = this.$('[data-kb-log-box]');
    if (box) {
      box.insertAdjacentHTML(
        'beforeend',
        `<div class="text-[11px] font-mono text-primary/80 border-l-2 border-primary/30 pl-2 py-0.5">${esc(String(line))}</div>`,
      );
      box.scrollTop = box.scrollHeight;
    }
    this._status = '处理中…';
    this._syncStatus();
  }

  /** @param {object} msg WebSocket knowledge_result */
  onResult(msg) {
    const text =
      msg?.content ||
      msg?.message ||
      msg?.markdown ||
      msg?.text ||
      msg?.result ||
      '';
    this._resultMd = String(text);
    this._step = 3;
    this._status = '归纳完成';
    this.update();
  }

  _syncStatus() {
    const el = this.$('[data-kb-status]');
    if (el) {
      el.textContent = this._status || '';
    }
  }

  destroy() {
    this._kbStoreBound = false;
    super.destroy();
  }
}
