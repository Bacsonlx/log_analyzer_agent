import { Component } from '../core/component.js';
import { esc, formatDuration, safeFetchJson } from '../utils/helpers.js';
import { getTemplateMeta } from '../templates/index.js';

const _DOT_COLOR = {
  success: 'bg-neon-green',
  failed: 'bg-accent-red',
  warning: 'bg-accent-yellow',
  skipped: 'bg-slate-600',
};

/**
 * 历史诊断记录卡片列表（最多展示 10 条），支持加载详情与删除
 */
export class HistoryList extends Component {
  /** 写入 store.taskHistory（供 main 初始化调用） */
  static async loadHistory(store, limit = 20) {
    try {
      const data = await safeFetchJson(`/api/history?limit=${limit}`);
      store.set('taskHistory', data.history || []);
    } catch (e) {
      console.error('loadHistory failed', e);
    }
  }

  _scoreBadge(score) {
    if (score == null || Number.isNaN(score)) {
      return '<span class="text-[10px] text-slate-600 font-mono">N/A</span>';
    }
    let cls = 'text-neon-green border-neon-green/40 bg-neon-green/10';
    if (score < 5) {
      cls = 'text-accent-red border-accent-red/40 bg-accent-red/10';
    } else if (score < 7.5) {
      cls = 'text-accent-yellow border-accent-yellow/40 bg-accent-yellow/10';
    }
    return `<span class="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${cls}">${score.toFixed(1)}</span>`;
  }

  _phaseDots(templateId, phaseStatuses) {
    if (!Array.isArray(phaseStatuses) || !phaseStatuses.length) return '';
    const meta = getTemplateMeta(templateId);
    const phaseNames = meta?.phases || [];
    const dots = phaseStatuses.map((st, i) => {
      const color = _DOT_COLOR[st] || _DOT_COLOR.skipped;
      const title = i < phaseNames.length ? esc(phaseNames[i]) : '';
      return `<span class="w-1.5 h-1.5 rounded-full inline-block ${color}" title="${title}"></span>`;
    }).join('');
    return `<span class="inline-flex items-center gap-1">${dots}</span>`;
  }

  _formatDate(startTime) {
    if (!startTime) return '';
    try {
      const d = new Date(startTime);
      if (Number.isNaN(d.getTime())) return '';
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      return `${mm}-${dd}`;
    } catch {
      return '';
    }
  }

  render() {
    const taskHistory = this.store.get('taskHistory') || [];
    const slice = Array.isArray(taskHistory) ? taskHistory.slice(0, 10) : [];

    const cards =
      slice.length === 0
        ? '<div class="text-center text-slate-600 text-xs py-6">暂无历史记录</div>'
        : slice
            .map((t) => {
              const file = t.file || '';
              const name = t.name || file || '未命名';
              const dur =
                t.duration_ms != null && t.duration_ms > 0
                  ? formatDuration(t.duration_ms)
                  : '';
              const cost =
                t.cost_usd != null && t.cost_usd > 0
                  ? `$${t.cost_usd.toFixed(2)}`
                  : '';
              const isFailed =
                t.has_failure ||
                (t.score != null && t.score !== undefined && t.score < 5) ||
                t.status === 'error';
              const ok = t.status === 'done' && !isFailed;
              const icon = ok
                ? '<span class="material-symbols-outlined text-neon-green text-base leading-none">check</span>'
                : '<span class="material-symbols-outlined text-accent-red text-base leading-none">close</span>';
              const encFile = encodeURIComponent(file);

              const templateBadge = t.template_label
                ? `<span class="text-[9px] font-bold px-1.5 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary">${esc(t.template_label)}</span>`
                : '';
              const scoreBadge = this._scoreBadge(t.score);
              const dateStr = this._formatDate(t.start_time);
              const dateFull = t.start_time || '';
              const dots = this._phaseDots(t.template_id, t.phase_statuses);
              const desc = t.description || '';

              return `<div class="bg-surface border border-primary/20 rounded-lg p-3 hover:border-primary/40 transition-all group relative cursor-pointer" data-history-open="${encFile}">
  <div class="flex items-center gap-1.5 mb-1.5">
    ${templateBadge}
    ${scoreBadge}
    <span class="flex-1"></span>
    ${dateStr ? `<span class="text-[10px] text-slate-600 font-mono" title="${esc(dateFull)}">${esc(dateStr)}</span>` : ''}
  </div>
  <div class="flex items-center gap-1.5 mb-1">
    ${icon}
    <p class="flex-1 text-xs font-bold text-slate-300 group-hover:text-primary transition-colors leading-snug truncate">${esc(name)}</p>
  </div>
  <div class="flex items-center gap-2 mb-1">
    ${dots}
    <span class="flex-1"></span>
    ${dur ? `<span class="text-[10px] text-slate-600 font-mono">${esc(dur)}</span>` : ''}
    ${cost ? `<span class="text-[10px] text-slate-600 font-mono">${esc(cost)}</span>` : ''}
  </div>
  ${desc ? `<p class="text-[11px] text-slate-500 truncate">${esc(desc)}</p>` : ''}
  <button type="button" data-history-delete="${encFile}" class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-slate-600 hover:text-accent-red transition-all p-0.5" title="删除">
    <span class="material-symbols-outlined text-sm">delete</span>
  </button>
</div>`;
            })
            .join('');

    return `
<div class="rounded-xl border border-primary/20 bg-surface/80 p-4 neon-border">
  <div class="flex items-center justify-between mb-3">
    <span class="text-[10px] uppercase tracking-widest text-primary/60 font-bold">历史记录</span>
  </div>
  <div data-history-list class="space-y-2 max-h-[420px] overflow-y-auto pr-1">${cards}</div>
</div>`;
  }

  onMount() {
    if (!this._historyClickBound) {
      this._historyClickBound = true;
      this._onHistoryClick = (e) => {
        const del = e.target.closest('[data-history-delete]');
        if (del) {
          e.stopPropagation();
          const raw = del.getAttribute('data-history-delete') || '';
          let filename = '';
          try {
            filename = decodeURIComponent(raw);
          } catch {
            filename = raw;
          }
          if (filename) this._deleteRecord(filename);
          return;
        }
        const open = e.target.closest('[data-history-open]');
        if (open) {
          const raw = open.getAttribute('data-history-open') || '';
          let filename = '';
          try {
            filename = decodeURIComponent(raw);
          } catch {
            filename = raw;
          }
          if (filename) this._loadDetail(filename);
        }
      };
      this.el.addEventListener('click', this._onHistoryClick);
    }

    if (!this._historyStoreBound) {
      this._historyStoreBound = true;
      this.subscribe('taskHistory', () => this.update());
    }
  }

  destroy() {
    if (this._historyClickBound && this._onHistoryClick) {
      this.el.removeEventListener('click', this._onHistoryClick);
      this._historyClickBound = false;
      this._onHistoryClick = null;
    }
    this._historyStoreBound = false;
    super.destroy();
  }

  /**
   * GET /api/history?limit=20，写入 store.taskHistory
   */
  async loadHistory() {
    return HistoryList.loadHistory(this.store);
  }

  async _loadDetail(filename) {
    try {
      const data = await safeFetchJson(`/api/history/${encodeURIComponent(filename)}`);
      if (data.error) {
        alert(data.error);
        return;
      }
      const safeName = (data.name || '').replace(/[/\\:*?"<>|]/g, '_');
      this.store.set('currentHistoryFile', filename);
      this.store.set('currentResultMd', data.result || '');
      this.store.set('currentResultName', safeName);
      this.store.set('resultFromLive', false);
      this.store.set('resultMeta', {
        duration_ms: data.duration_ms || 0,
        cost_usd: data.cost_usd || 0,
        tool_count: data.tool_count || 0,
        score: data.score,
        has_failure: data.has_failure,
        fromLive: false,
        status: data.has_failure ? 'warning' : 'success',
        template_data: data.template_data || null,
        extracted_files: data.extracted_files || [],
      });
      if (this.store.get('view') === 'result') {
        this.store.set('view', 'idle');
        queueMicrotask(() => this.store.set('view', 'result'));
      } else {
        this.store.set('view', 'result');
      }
    } catch (e) {
      alert(`加载失败: ${e.message}`);
    }
  }

  async _deleteRecord(filename) {
    if (!confirm('确定删除这条历史记录？')) return;
    try {
      const data = await safeFetchJson(`/api/history/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      });
      if (data.error) {
        alert(data.error);
        return;
      }
      await this.loadHistory();
    } catch (e) {
      alert(`删除失败: ${e.message}`);
    }
  }
}
