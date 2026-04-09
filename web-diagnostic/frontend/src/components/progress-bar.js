import { Component } from '../core/component.js';

/**
 * 细进度条 + 百分比文案，订阅 store.progress
 */
export class ProgressBar extends Component {
  constructor(container, store) {
    super(container, store);
    this._pct = 0;
  }

  render() {
    const p = Math.max(0, Math.min(100, this._pct));
    return `
<div class="rounded-lg border border-primary/15 bg-surface/60 px-3 py-2.5 neon-border">
  <div class="flex items-center justify-between gap-2 mb-1.5">
    <span class="text-[10px] uppercase tracking-widest text-primary/50 font-bold">进度</span>
    <span class="text-xs font-mono text-primary tabular-nums shadow-[0_0_8px_rgba(61,199,245,0.35)]" data-progress-label>${p}%</span>
  </div>
  <div class="h-1.5 w-full rounded-full bg-bg-dark overflow-hidden border border-primary/10">
    <div
      class="h-full rounded-full bg-gradient-to-r from-primary via-neon-green/80 to-primary transition-all duration-300 ease-out shadow-[0_0_12px_rgba(61,199,245,0.65),0_0_6px_rgba(0,255,157,0.35)]"
      style="width: ${p}%"
      data-progress-fill
    ></div>
  </div>
</div>`;
  }

  onMount() {
    this._pct = Number(this.store.get('progress')) || 0;
    this._applyPct(this._pct);
    if (!this._progressStoreBound) {
      this._progressStoreBound = true;
      this.subscribe('progress', (v) => {
        this._pct = Math.max(0, Math.min(100, Number(v) || 0));
        this._applyPct(this._pct);
      });
    }
  }

  _applyPct(p) {
    const fill = this.$('[data-progress-fill]');
    const label = this.$('[data-progress-label]');
    if (fill) {
      fill.style.width = `${p}%`;
    }
    if (label) {
      label.textContent = `${Math.round(p)}%`;
    }
  }

  /** @param {number} pct 0–100 */
  setProgress(pct) {
    this._pct = Math.max(0, Math.min(100, Number(pct) || 0));
    this.store.set('progress', this._pct);
    this._applyPct(this._pct);
  }
}
