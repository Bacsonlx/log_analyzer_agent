import { Component } from '../core/component.js';
import { esc, formatToolName } from '../utils/helpers.js';

/**
 * 工具调用步骤时间线：订阅 store.steps，支持 addStep / completeLastStep
 */
export class StepsPanel extends Component {
  render() {
    const steps = this.store.get('steps') || [];
    const items = steps
      .map((s, i) => this._stepRow(s, i === steps.length - 1))
      .join('');
    return `
<div class="flex flex-col h-full min-h-0 rounded-lg border border-neon-purple/20 bg-surface/80 neon-border overflow-hidden">
  <div class="px-3 py-2 border-b border-neon-purple/15 bg-bg-dark/50 flex items-center gap-2 flex-shrink-0">
    <span class="material-symbols-outlined text-neon-purple text-base">timeline</span>
    <span class="text-[10px] font-bold uppercase tracking-widest text-neon-purple/80">工具步骤</span>
  </div>
  <div class="flex-1 min-h-0 overflow-y-auto p-3 space-y-0" data-steps-scroll>
    ${items || `<p class="text-[10px] text-slate-600 text-center py-6">等待工具调用…</p>`}
  </div>
</div>`;
  }

  _stepRow(step, isLast) {
    const name = formatToolName(step.name || '');
    const done = step.status === 'done';
    const icon = done
      ? `<span class="material-symbols-outlined text-neon-green text-lg">check_circle</span>`
      : `<span class="relative flex h-6 w-6 items-center justify-center">
          <span class="absolute h-2.5 w-2.5 rounded-full bg-primary shadow-[0_0_10px_rgba(61,199,245,0.8)] pulse-neon"></span>
        </span>`;
    const textCls = done ? 'text-slate-300' : 'text-primary font-medium';
    const lastCls = isLast ? '' : 'step-line';
    return `
<div class="relative flex gap-3 pl-0 ${lastCls} pb-4" data-step-row>
  <div class="flex-shrink-0 w-6 flex justify-center pt-0.5">${icon}</div>
  <div class="min-w-0 flex-1 pt-0.5">
    <p class="text-[11px] leading-snug break-words ${textCls}">${esc(name)}</p>
  </div>
</div>`;
  }

  onMount() {
    if (!this._stepsStoreBound) {
      this._stepsStoreBound = true;
      this.subscribe('steps', () => {
        this.update();
        queueMicrotask(() => this._scrollToLatest());
      });
    }
  }

  _scrollToLatest() {
    const sc = this.$('[data-steps-scroll]');
    if (sc) {
      sc.scrollTop = sc.scrollHeight;
    }
  }

  /** @param {string} name @param {'active'|'done'} status */
  addStep(name, status = 'active') {
    const steps = [...(this.store.get('steps') || [])];
    steps.push({ name, status });
    this.store.set('steps', steps);
  }

  completeLastStep() {
    const steps = [...(this.store.get('steps') || [])];
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].status === 'active') {
        steps[i] = { ...steps[i], status: 'done' };
        this.store.set('steps', steps);
        return;
      }
    }
  }
}
