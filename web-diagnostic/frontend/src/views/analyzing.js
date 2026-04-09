import { Component } from '../core/component.js';
import { Terminal } from '../components/terminal.js';
import { ProgressBar } from '../components/progress-bar.js';
import { StepsPanel } from '../components/steps-panel.js';
import { esc, formatDuration } from '../utils/helpers.js';

/**
 * 分析中：左信息 + 中终端 + 右步骤时间线
 */
export class AnalyzingView extends Component {
  constructor(container, store) {
    super(container, store);
    this._terminal = null;
    this._progress = null;
    this._steps = null;
    this._elapsedTimer = null;
  }

  render() {
    const title = esc(
      (this.store.get('activeTaskTitle') || '诊断任务').slice(0, 80),
    );
    const fileName = esc(this.store.get('activeTaskFile') || '');

    return `
<div class="flex h-full min-h-0 gap-4 p-4 cyber-grid">
  <aside class="w-56 flex-shrink-0 flex flex-col gap-4 min-h-0">
    <div class="rounded-lg border border-primary/20 bg-surface/80 p-3 neon-border space-y-2">
      <span class="text-[10px] uppercase tracking-widest text-primary/50 font-bold">当前任务</span>
      <p class="text-xs font-semibold text-slate-200 leading-snug break-words" data-task-title>${title}</p>
      <p class="text-[10px] text-slate-500 font-mono break-all" data-task-file>${fileName}</p>
    </div>
    <div data-progress-host></div>
    <div class="rounded-lg border border-surface-2 bg-bg-dark/80 px-3 py-2">
      <span class="text-[10px] text-slate-500 uppercase tracking-wider">已用时</span>
      <p class="text-lg font-mono text-primary neon-glow mt-0.5" data-elapsed-display>0s</p>
    </div>
    <button
      type="button"
      data-stop-analysis
      class="w-full py-2 rounded-lg border border-accent-red/40 bg-accent-red/10 text-accent-red text-xs font-bold uppercase tracking-wider hover:bg-accent-red/20 transition-colors flex items-center justify-center gap-1"
    >
      <span class="material-symbols-outlined text-base">stop_circle</span>
      停止
    </button>
  </aside>

  <div class="flex-1 min-w-0 flex flex-col min-h-0 bg-bg-dark rounded-lg border border-surface-2/80 p-1 shadow-inner">
    <div class="flex-1 min-h-0 flex flex-col min-h-[280px] bg-black/30 rounded-md" data-terminal-host></div>
  </div>

  <aside class="w-56 flex-shrink-0 min-h-0 flex flex-col">
    <div class="flex-1 min-h-0" data-steps-host></div>
  </aside>
</div>`;
  }

  onMount() {
    const th = this.$('[data-terminal-host]');
    if (th) {
      this._terminal = new Terminal(th, this.store);
      this._terminal.mount();
    }
    const ph = this.$('[data-progress-host]');
    if (ph) {
      this._progress = new ProgressBar(ph, this.store);
      this._progress.mount();
    }
    const sh = this.$('[data-steps-host]');
    if (sh) {
      this._steps = new StepsPanel(sh, this.store);
      this._steps.mount();
    }

    if (!this.store.diag) this.store.diag = {};
    this.store.diag.terminal = this._terminal;
    this.store.diag.stepsPanel = this._steps;
    this.store.diag.analyzingView = this;

    this.on('[data-stop-analysis]', 'click', () => this._stop());

    this.subscribe('activeTaskTitle', () => this._syncTaskLabels());
    this.subscribe('activeTaskFile', () => this._syncTaskLabels());
    this.subscribe('analysisStartTime', () => this.startTimer());

    this.startTimer();
  }

  _syncTaskLabels() {
    const t = this.$('[data-task-title]');
    const f = this.$('[data-task-file]');
    if (t) {
      t.textContent = (this.store.get('activeTaskTitle') || '诊断任务').slice(
        0,
        80,
      );
    }
    if (f) f.textContent = this.store.get('activeTaskFile') || '';
  }

  _stop() {
    this.store.set('taskAction', { type: 'stopAnalysis', ts: Date.now() });
  }

  startTimer() {
    this.stopTimer();
    this._elapsedTimer = setInterval(() => this._tickElapsed(), 500);
    this._tickElapsed();
  }

  stopTimer() {
    if (this._elapsedTimer) {
      clearInterval(this._elapsedTimer);
      this._elapsedTimer = null;
    }
  }

  _tickElapsed() {
    const el = this.$('[data-elapsed-display]');
    if (!el) return;
    const start = this.store.get('analysisStartTime');
    if (typeof start !== 'number' || start <= 0) {
      el.textContent = formatDuration(0);
      return;
    }
    el.textContent = formatDuration(Date.now() - start);
  }

  destroy() {
    this.stopTimer();
    if (this.store.diag) {
      if (this.store.diag.terminal === this._terminal) {
        this.store.diag.terminal = null;
      }
      if (this.store.diag.stepsPanel === this._steps) {
        this.store.diag.stepsPanel = null;
      }
      if (this.store.diag.analyzingView === this) {
        this.store.diag.analyzingView = null;
      }
    }
    this._terminal?.destroy();
    this._terminal = null;
    this._progress?.destroy();
    this._progress = null;
    this._steps?.destroy();
    this._steps = null;
    super.destroy();
  }
}
