import { Component } from '../core/component.js';
import { esc, escAttr } from '../utils/helpers.js';

function parseTaskId(raw) {
  if (raw == null || raw === '') return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : raw;
}

/**
 * 任务队列表格；通过 store.taskAction 派发 removeTask / stopAnalysis（宿主订阅处理）
 */
export class TaskQueue extends Component {
  render() {
    const taskQueue = this.store.get('taskQueue') || [];
    const rows =
      taskQueue.length === 0
        ? `<tr><td colspan="3" class="px-4 py-6 text-center text-slate-600 text-xs">暂无任务</td></tr>`
        : taskQueue
            .map((t) => {
              const statusMap = {
                queued:
                  '<span class="bg-primary/10 text-primary text-[9px] px-2 py-0.5 border border-primary/20 rounded uppercase font-bold">排队中</span>',
                waiting:
                  '<span class="bg-accent-yellow/10 text-accent-yellow text-[9px] px-2 py-0.5 border border-accent-yellow/20 rounded uppercase font-bold">等待中</span>',
                running: `<div class="flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full bg-neon-green pulse-neon"></span>
                  <span class="text-neon-green text-[10px] font-bold uppercase">分析中</span>
                </div>`,
                done:
                  '<span class="text-neon-green text-[10px] font-bold uppercase">完成</span>',
                stopped:
                  '<span class="text-slate-500 text-[10px] font-bold uppercase">已停止</span>',
                error:
                  '<span class="text-accent-red text-[10px] font-bold uppercase">出错</span>',
              };
              const badge = statusMap[t.status] || '';
              const labelRaw =
                (t.fileName && String(t.fileName).trim()) ||
                (t.name && String(t.name)) ||
                (t.message && String(t.message)) ||
                '—';
              const label =
                labelRaw.length > 48 ? `${labelRaw.slice(0, 48)}…` : labelRaw;

              let actions = '';
              if (t.status === 'queued' || t.status === 'waiting') {
                actions = `<button type="button" data-queue-remove="${t.id}" class="text-slate-500 hover:text-accent-red transition-colors" title="移除">
                  <span class="material-symbols-outlined text-lg">delete</span>
                </button>`;
              } else if (t.status === 'running') {
                actions = `<button type="button" data-queue-stop="${t.id}" data-queue-server-id="${escAttr(String(t.serverTaskId || ''))}" class="text-accent-red hover:bg-accent-red/10 p-1 rounded transition-colors" title="停止">
                  <span class="material-symbols-outlined text-lg">stop_circle</span>
                </button>`;
              }

              return `<tr class="hover:bg-primary/5 transition-colors border-b border-primary/10 last:border-0">
      <td class="px-4 py-2.5 text-slate-300 text-xs">${esc(label)}</td>
      <td class="px-4 py-2.5">${badge}</td>
      <td class="px-4 py-2.5 text-right">${actions}</td>
    </tr>`;
            })
            .join('');

    return `
<div class="rounded-xl border border-primary/20 bg-surface/80 overflow-hidden neon-border">
  <div class="px-4 py-2 border-b border-primary/15 bg-surface-2/50">
    <span class="text-[10px] uppercase tracking-widest text-primary/60 font-bold">任务队列</span>
  </div>
  <div class="overflow-x-auto">
    <table class="w-full text-left">
      <thead>
        <tr class="text-[10px] uppercase tracking-widest text-primary/40 border-b border-primary/15">
          <th class="px-4 py-2 font-bold">任务</th>
          <th class="px-4 py-2 font-bold">状态</th>
          <th class="px-4 py-2 font-bold text-right">操作</th>
        </tr>
      </thead>
      <tbody data-queue-body>${rows}</tbody>
    </table>
  </div>
</div>`;
  }

  onMount() {
    const body = this.$('[data-queue-body]');
    if (!body) return;

    body.addEventListener('click', (e) => {
      const rm = e.target.closest('[data-queue-remove]');
      if (rm) {
        const id = parseTaskId(rm.getAttribute('data-queue-remove'));
        this.store.set('taskAction', {
          type: 'removeTask',
          taskId: id,
          ts: Date.now(),
        });
        return;
      }
      const st = e.target.closest('[data-queue-stop]');
      if (st) {
        const taskId = parseTaskId(st.getAttribute('data-queue-stop'));
        const serverTaskId =
          st.getAttribute('data-queue-server-id') || '';
        this.store.set('taskAction', {
          type: 'stopAnalysis',
          taskId,
          serverTaskId,
          ts: Date.now(),
        });
      }
    });

    if (!this._queueStoreBound) {
      this._queueStoreBound = true;
      this.subscribe('taskQueue', () => this.update());
    }
  }

  destroy() {
    this._queueStoreBound = false;
    super.destroy();
  }
}
