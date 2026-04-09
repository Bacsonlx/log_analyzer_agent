import { Component } from '../core/component.js';
import { esc, formatDuration } from '../utils/helpers.js';

/** 标签 → Tailwind 文字色类 */
const TAG_COLORS = {
  SYSTEM: 'text-primary/40',
  TOOL: 'text-neon-purple',
  DATA: 'text-primary/60',
  AI: 'text-slate-400',
  DONE: 'text-neon-green',
  ERROR: 'text-accent-red',
};

/**
 * 实时终端日志：扫描线背景、按标签着色、事件计数、自动滚动
 */
export class Terminal extends Component {
  constructor(container, store) {
    super(container, store);
    this._elapsedTimer = null;
  }

  render() {
    const events = this.store.get('eventCount') || 0;
    return `
<div class="flex flex-col h-full min-h-0 rounded-lg border border-primary/20 bg-bg-dark neon-border relative overflow-hidden shadow-[0_0_24px_rgba(61,199,245,0.06)]">
  <div class="scanline absolute inset-0 z-10 pointer-events-none" aria-hidden="true"></div>
  <div class="relative z-20 flex items-center justify-between gap-2 px-3 py-2 border-b border-primary/10 bg-surface/90 backdrop-blur-sm flex-shrink-0">
    <div class="flex items-center gap-2 min-w-0">
      <span class="material-symbols-outlined text-primary text-lg">terminal</span>
      <span class="text-[10px] font-bold uppercase tracking-widest text-primary/70">诊断输出</span>
    </div>
    <div class="flex items-center gap-3 flex-shrink-0">
      <span class="text-[10px] font-mono text-slate-500 hidden sm:inline" data-live-elapsed title="Session elapsed">Δ 0.0s</span>
      <span class="text-[10px] font-mono text-neon-green/90 tabular-nums" data-event-count>EVENTS ${events}</span>
    </div>
  </div>
  <div class="relative z-0 flex-1 min-h-0 overflow-y-auto overflow-x-auto p-3 font-mono text-[11px] leading-relaxed" data-terminal-body></div>
</div>`;
  }

  onMount() {
    this._bindElapsedTick();
    if (!this._terminalStoreBound) {
      this._terminalStoreBound = true;
      this.subscribe('analysisStartTime', () => this._bindElapsedTick());
      this.subscribe('eventCount', () => this._syncEventCount());
    }
  }

  _syncEventCount() {
    const el = this.$('[data-event-count]');
    if (el) {
      el.textContent = `EVENTS ${this.store.get('eventCount') || 0}`;
    }
  }

  _bindElapsedTick() {
    if (this._elapsedTimer) {
      clearInterval(this._elapsedTimer);
      this._elapsedTimer = null;
    }
    const tick = () => {
      const live = this.$('[data-live-elapsed]');
      if (!live) {
        return;
      }
      const start = this.store.get('analysisStartTime');
      if (typeof start !== 'number' || start <= 0) {
        live.textContent = 'Δ 0.0s';
        return;
      }
      live.textContent = `Δ ${formatDuration(Date.now() - start)}`;
    };
    tick();
    this._elapsedTimer = setInterval(tick, 250);
  }

  /**
   * 追加一行日志（elapsed 为写入时刻相对 analysisStartTime）
   * @param {keyof typeof TAG_COLORS} tag
   * @param {string} text
   */
  termLog(tag, text) {
    const body = this.$('[data-terminal-body]');
    if (!body) {
      return;
    }
    const tagKey = String(tag || 'SYSTEM').toUpperCase();
    const start = this.store.get('analysisStartTime');
    const elapsedSec =
      typeof start === 'number' && start > 0
        ? formatDuration(Date.now() - start)
        : '0.0s';
    const color = TAG_COLORS[tagKey] || TAG_COLORS.SYSTEM;
    const line = document.createElement('div');
    line.className = `term-line py-0.5 px-1 -mx-1 rounded border border-transparent hover:bg-primary/[0.06] hover:border-primary/10 transition-colors ${color}`;
    line.innerHTML = `<span class="text-slate-600">[ ${esc(elapsedSec)} ]</span> <span class="font-bold">[ ${esc(tagKey)} ]</span> <span>${esc(text)}</span>`;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
  }

  /** 清空终端（新任务开始时由 main 调用） */
  clear() {
    const body = this.$('[data-terminal-body]');
    if (body) {
      body.innerHTML = '';
    }
  }

  destroy() {
    if (this._elapsedTimer) {
      clearInterval(this._elapsedTimer);
      this._elapsedTimer = null;
    }
    super.destroy();
  }
}
