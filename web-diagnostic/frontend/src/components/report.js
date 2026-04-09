import { Component } from '../core/component.js';
import {
  esc,
  copyToClipboard,
  parseScore,
  stripScoreLine,
  timestamp,
} from '../utils/helpers.js';
import { renderMarkdown, highlightAll } from '../utils/markdown.js';
import { getTemplateMeta } from '../templates/index.js';

/**
 * Markdown 报告：状态条、可信度、TOC、操作按钮
 */
export class Report extends Component {
  constructor(container, store) {
    super(container, store);
    this._md = '';
    this._meta = {};
    this._fromLive = false;
    this._renderMode = 'markdown'; // 'markdown' | 'timeline'
  }

  render() {
    if (this._renderMode === 'timeline') {
      return this._renderTimeline();
    }
    return this._renderMarkdown();
  }

  _renderMarkdown() {
    const { banner, bannerBorder } = this._bannerStyle();
    const score = this._scoreValue();
    const scoreBadge = this._scoreBadgeHtml(score);
    const bodyHtml = this._md
      ? renderMarkdown(stripScoreLine(this._md))
      : '<p class="text-slate-500 text-sm">暂无报告内容</p>';
    const toc = this._buildTocPlaceholder();
    const extractedFiles = Array.isArray(this._meta.extracted_files) ? this._meta.extracted_files : [];
    const extractedFilesHtml = this._buildExtractedFilesHtml(extractedFiles);

    return `
<div class="flex flex-col gap-4 min-h-0">
  <div class="rounded-lg border border-primary/20 bg-surface/90 neon-border px-4 py-3 border-l-4 ${bannerBorder}">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <div class="flex items-center gap-3 min-w-0">
        <span class="material-symbols-outlined text-2xl shrink-0 ${banner.iconCls}">${esc(banner.icon)}</span>
        <div class="min-w-0">
          <p class="text-sm font-bold text-slate-100">${esc(banner.title)}</p>
          <p class="text-[11px] text-slate-500 mt-0.5">${esc(banner.sub)}</p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">${scoreBadge}</div>
    </div>
  </div>

  <div class="flex flex-col lg:flex-row gap-4 min-h-0 flex-1">
    <nav class="lg:w-52 flex-shrink-0 lg:sticky lg:top-0 lg:self-start max-h-[40vh] lg:max-h-[calc(100vh-8rem)] overflow-y-auto rounded-lg border border-primary/15 bg-bg-dark/80 p-3" data-report-toc-wrap>
      <p class="text-[10px] uppercase tracking-widest text-primary/50 font-bold mb-2">目录</p>
      <div class="space-y-1 text-xs" data-report-toc>${toc}</div>
    </nav>
    <article class="flex-1 min-w-0 rounded-lg border border-primary/15 bg-surface/40 p-4 sm:p-6 overflow-x-auto">
      <div class="report-content text-sm" data-report-body>${bodyHtml}</div>
    </article>
  </div>

  ${extractedFilesHtml}

  <div class="flex flex-wrap gap-2 justify-center sm:justify-start pb-2">
    <button type="button" data-action-kb class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-neon-purple/40 bg-neon-purple/10 text-neon-purple text-xs font-bold uppercase tracking-wider hover:bg-neon-purple/20 transition-colors">
      <span class="material-symbols-outlined text-base">library_add</span>
      归纳到知识库
    </button>
    <button type="button" data-action-share class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-primary/30 bg-primary/10 text-primary text-xs font-bold uppercase tracking-wider hover:bg-primary/20 transition-colors">
      <span class="material-symbols-outlined text-base">share</span>
      分享链接
    </button>
    <button type="button" data-action-download class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-600 bg-surface text-slate-200 text-xs font-bold uppercase tracking-wider hover:border-primary/40 transition-colors">
      <span class="material-symbols-outlined text-base">download</span>
      下载报告
    </button>
    <button type="button" data-action-home class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-600 bg-bg-dark text-slate-300 text-xs font-bold uppercase tracking-wider hover:border-primary/30 transition-colors">
      <span class="material-symbols-outlined text-base">home</span>
      返回首页
    </button>
  </div>
</div>`;
  }

  _renderTimeline() {
    const { banner, bannerBorder } = this._bannerStyle();
    const score = this._scoreValue();
    const scoreBadge = this._scoreBadgeHtml(score);
    const td = this._meta.template_data || {};
    const templateMeta = getTemplateMeta(td.template);
    const templateLabel = templateMeta ? templateMeta.label : (td.template || '');
    const recordings = Array.isArray(td.recordings) ? td.recordings : [];
    const extractedFiles = Array.isArray(this._meta.extracted_files) ? this._meta.extracted_files : [];
    const extractedFilesHtml = this._buildExtractedFilesHtml(extractedFiles);
    const summaryHtml = this._md
      ? renderMarkdown(stripScoreLine(this._md))
      : '';

    const recSummary = this._buildRecordingsSummary(recordings);
    const recordingsHtml = recordings.length
      ? this._buildRecordingsHtml(recordings)
      : '<p class="text-slate-500 text-sm">暂无录音流程数据</p>';

    return `
<div class="flex flex-col gap-4 min-h-0">
  <div class="rounded-lg border border-primary/20 bg-surface/90 neon-border px-4 py-3 border-l-4 ${bannerBorder}">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <div class="flex items-center gap-3 min-w-0">
        <span class="material-symbols-outlined text-2xl shrink-0 ${banner.iconCls}">${esc(banner.icon)}</span>
        <div class="min-w-0">
          <p class="text-sm font-bold text-slate-100">${esc(banner.title)}</p>
          <p class="text-[11px] text-slate-500 mt-0.5">${esc(banner.sub)}</p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        ${templateLabel ? `<span class="text-[10px] font-mono px-2 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary">${esc(templateLabel)}</span>` : ''}
        ${recSummary}
        ${scoreBadge}
      </div>
    </div>
  </div>

  <div class="space-y-3">
    ${recordingsHtml}
  </div>

  ${summaryHtml ? `
  <details class="rounded-lg border border-primary/15 bg-surface/40">
    <summary class="px-4 py-3 text-xs font-bold text-slate-400 cursor-pointer hover:text-slate-200 flex items-center gap-2">
      <span class="material-symbols-outlined text-base">description</span>
      诊断报告详情
    </summary>
    <div class="px-4 pb-4 report-content text-sm" data-report-body>${summaryHtml}</div>
  </details>` : ''}

  ${extractedFilesHtml}

  <div class="flex flex-wrap gap-2 justify-center sm:justify-start pb-2">
    <button type="button" data-action-kb class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-neon-purple/40 bg-neon-purple/10 text-neon-purple text-xs font-bold uppercase tracking-wider hover:bg-neon-purple/20 transition-colors">
      <span class="material-symbols-outlined text-base">library_add</span>
      归纳到知识库
    </button>
    <button type="button" data-action-share class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-primary/30 bg-primary/10 text-primary text-xs font-bold uppercase tracking-wider hover:bg-primary/20 transition-colors">
      <span class="material-symbols-outlined text-base">share</span>
      分享链接
    </button>
    <button type="button" data-action-download class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-600 bg-surface text-slate-200 text-xs font-bold uppercase tracking-wider hover:border-primary/40 transition-colors">
      <span class="material-symbols-outlined text-base">download</span>
      下载报告
    </button>
    <button type="button" data-action-home class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-600 bg-bg-dark text-slate-300 text-xs font-bold uppercase tracking-wider hover:border-primary/30 transition-colors">
      <span class="material-symbols-outlined text-base">home</span>
      返回首页
    </button>
  </div>
</div>`;
  }

  _buildTimelineHtml(phases) {
    if (!phases.length) return '<p class="text-slate-500 text-sm">暂无流程数据</p>';

    const statusConfig = {
      success: { dot: 'bg-neon-green border-neon-green/60', icon: 'check_circle', iconCls: 'text-neon-green', label: '成功' },
      failed:  { dot: 'bg-accent-red border-accent-red/60',   icon: 'cancel',       iconCls: 'text-accent-red',   label: '失败' },
      warning: { dot: 'bg-accent-yellow border-accent-yellow/60', icon: 'warning',  iconCls: 'text-accent-yellow', label: '警告' },
      skipped: { dot: 'bg-slate-600 border-slate-500',          icon: 'remove_circle_outline', iconCls: 'text-slate-500', label: '未找到' },
    };

    return phases.map((p, i) => {
      const cfg = statusConfig[p.status] || statusConfig.skipped;
      const isLast = i === phases.length - 1;
      const timeStr = p.time ? `<span class="font-mono text-[10px] text-slate-500 ml-2">${esc(p.time)}</span>` : '';
      const detailStr = p.detail ? `<p class="text-[11px] text-slate-400 mt-1 leading-relaxed">${esc(p.detail)}</p>` : '';
      const connectorCls = isLast ? 'invisible' : `border-l-2 ${p.status === 'failed' ? 'border-accent-red/30' : p.status === 'warning' ? 'border-accent-yellow/30' : p.status === 'success' ? 'border-neon-green/30' : 'border-slate-700'}`;

      return `
<div class="flex gap-3">
  <div class="flex flex-col items-center">
    <div class="w-7 h-7 rounded-full border-2 ${cfg.dot} flex items-center justify-center shrink-0 z-10">
      <span class="material-symbols-outlined text-sm ${cfg.iconCls}" style="font-size:14px">${esc(cfg.icon)}</span>
    </div>
    <div class="flex-1 ${connectorCls} mt-1 mb-1" style="min-height:20px"></div>
  </div>
  <div class="pb-4 min-w-0 flex-1 pt-0.5">
    <div class="flex flex-wrap items-baseline gap-1">
      <span class="text-sm font-semibold text-slate-200">${esc(p.name)}</span>
      <span class="text-[10px] font-bold uppercase tracking-wider ${cfg.iconCls}">${esc(cfg.label)}</span>
      ${timeStr}
    </div>
    ${detailStr}
  </div>
</div>`;
    }).join('');
  }

  _buildRecordingsSummary(recordings) {
    if (!recordings.length) return '';
    const total = recordings.length;
    const success = recordings.filter(r => r.status === 'success').length;
    const failed = recordings.filter(r => r.status === 'failed').length;
    const interrupted = recordings.filter(r => r.status === 'interrupted').length;
    const parts = [`${total} 段录音`];
    if (success) parts.push(`${success} 成功`);
    if (failed) parts.push(`${failed} 失败`);
    if (interrupted) parts.push(`${interrupted} 中断`);
    return `<span class="text-[10px] font-mono px-2 py-0.5 rounded border border-slate-600 bg-bg-dark text-slate-400">${esc(parts.join(' · '))}</span>`;
  }

  _buildRecordingsHtml(recordings) {
    const recStatusCfg = {
      success:     { border: 'border-neon-green/30', icon: 'check_circle', iconCls: 'text-neon-green', label: '成功' },
      failed:      { border: 'border-accent-red/30', icon: 'cancel', iconCls: 'text-accent-red', label: '失败' },
      interrupted: { border: 'border-accent-yellow/30', icon: 'warning', iconCls: 'text-accent-yellow', label: '中断' },
    };
    const shouldAutoOpen = recordings.length <= 3;

    return recordings.map((rec, idx) => {
      const cfg = recStatusCfg[rec.status] || recStatusCfg.success;
      const phases = Array.isArray(rec.phases) ? rec.phases : [];
      const asrRecords = Array.isArray(rec.asr_records) ? rec.asr_records : [];
      const timelineHtml = this._buildIntegratedTimelineHtml(phases, asrRecords);
      const rid = rec.record_id || '';
      const isOpen = shouldAutoOpen || rec.status !== 'success';

      return `
<details class="rounded-lg border ${cfg.border} bg-surface/40 group" ${isOpen ? 'open' : ''}>
  <summary class="flex flex-wrap items-center gap-2 px-4 py-3 cursor-pointer list-none select-none hover:bg-primary/5 rounded-lg transition-colors">
    <span class="material-symbols-outlined text-lg ${cfg.iconCls}">${esc(cfg.icon)}</span>
    <span class="text-sm font-bold text-slate-200">#${idx + 1}</span>
    <span class="text-[11px] font-mono text-slate-400 select-all truncate max-w-[300px]" title="${esc(rid)}">${esc(rid)}</span>
    <span class="ml-auto flex items-center gap-2 shrink-0">
      ${asrRecords.length ? `<span class="text-[10px] text-slate-500">${asrRecords.length} 句</span>` : ''}
      <span class="text-[10px] font-bold ${cfg.iconCls}">${esc(cfg.label)}</span>
    </span>
  </summary>
  <div class="px-4 pb-4 pt-2 border-t ${cfg.border}">
    <div class="timeline-phases">${timelineHtml}</div>
  </div>
</details>`;
    }).join('');
  }

  _buildIntegratedTimelineHtml(phases, asrRecords) {
    if (!phases.length) return '<p class="text-slate-500 text-sm">暂无流程数据</p>';

    const statusConfig = {
      success: { dot: 'bg-neon-green border-neon-green/60', icon: 'check_circle', iconCls: 'text-neon-green', label: '成功' },
      failed:  { dot: 'bg-accent-red border-accent-red/60',   icon: 'cancel',       iconCls: 'text-accent-red',   label: '失败' },
      warning: { dot: 'bg-accent-yellow border-accent-yellow/60', icon: 'warning',  iconCls: 'text-accent-yellow', label: '警告' },
      skipped: { dot: 'bg-slate-600 border-slate-500',          icon: 'remove_circle_outline', iconCls: 'text-slate-500', label: '未找到' },
    };

    const asrStatusCfg = {
      success: { cls: 'text-neon-green',    dot: 'bg-neon-green',    label: '✓' },
      empty:   { cls: 'text-accent-yellow', dot: 'bg-accent-yellow', label: '⚠' },
      error:   { cls: 'text-accent-red',    dot: 'bg-accent-red',    label: '✗' },
    };

    return phases.map((p, i) => {
      const cfg = statusConfig[p.status] || statusConfig.skipped;
      const isLast = i === phases.length - 1;
      const timeStr = p.time ? `<span class="font-mono text-[10px] text-slate-500 ml-2">${esc(p.time)}</span>` : '';
      const detailStr = p.detail ? `<p class="text-[11px] text-slate-400 mt-1 leading-relaxed">${esc(p.detail)}</p>` : '';

      const isRecognitionStart = p.name === '开始识别';
      const hasAsrBelow = isRecognitionStart && asrRecords.length > 0;
      const connectorCls = isLast && !hasAsrBelow
        ? 'invisible'
        : `border-l-2 ${p.status === 'failed' ? 'border-accent-red/30' : p.status === 'warning' ? 'border-accent-yellow/30' : p.status === 'success' ? 'border-neon-green/30' : 'border-slate-700'}`;

      let asrSubItems = '';
      if (hasAsrBelow) {
        asrSubItems = asrRecords.map((r, idx) => {
          const aCfg = asrStatusCfg[r.status] || asrStatusCfg.success;
          const durationStr = r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : '';
          const aTimeStr = r.start_time || '';
          const textDisplay = r.final_text
            ? esc(r.final_text)
            : '（无识别结果）';
          const translationStr = r.translation
            ? ` → ${esc(r.translation)}`
            : '';
          const isLastAsr = idx === asrRecords.length - 1;
          const connector = isLastAsr ? '└─' : '├─';

          const updates = Array.isArray(r.updates) ? r.updates : [];
          const updatesHtml = updates.map((u) =>
            `<div class="flex gap-2 text-[10px]">
              <span class="font-mono text-slate-600 shrink-0 w-20">${esc(u.time || '')}</span>
              <span class="text-slate-500">${esc(u.text || '')}</span>
            </div>`
          ).join('');
          const endRow = r.end_time ? `<div class="flex gap-2 text-[10px] mt-0.5">
            <span class="font-mono text-slate-600 shrink-0 w-20">${esc(r.end_time)}</span>
            <span class="${aCfg.cls} font-bold">ended</span>
            ${durationStr ? `<span class="text-slate-500">· ${esc(durationStr)}</span>` : ''}
            ${r.error ? `<span class="text-accent-red">· ${esc(String(r.error))}</span>` : ''}
          </div>` : '';
          const hasDetail = updates.length > 0 || r.end_time;

          if (hasDetail) {
            return `
  <details class="ml-6 group/asr">
    <summary class="flex flex-wrap items-center gap-1.5 py-0.5 cursor-pointer list-none select-none hover:bg-primary/5 rounded px-1 -ml-1 transition-colors text-[11px]">
      <span class="text-slate-600 font-mono shrink-0">${connector}</span>
      <span class="w-1.5 h-1.5 rounded-full shrink-0 ${aCfg.dot}"></span>
      <span class="font-mono text-slate-600 shrink-0">⑴</span>
      <span class="text-slate-200">${textDisplay}${translationStr}</span>
      <span class="ml-auto flex items-center gap-1.5 shrink-0">
        ${durationStr ? `<span class="font-mono text-slate-500 text-[10px]">${esc(durationStr)}</span>` : ''}
        <span class="font-bold ${aCfg.cls}">${aCfg.label}</span>
        ${aTimeStr ? `<span class="font-mono text-slate-600 text-[10px]">${esc(aTimeStr)}</span>` : ''}
      </span>
    </summary>
    <div class="ml-8 pl-3 border-l border-primary/10 pb-1 pt-0.5 space-y-0.5">
      ${updatesHtml || '<p class="text-[10px] text-slate-600">无中间更新</p>'}
      ${endRow}
    </div>
  </details>`.replace('⑴', `${idx + 1}`);
          }

          return `
  <div class="ml-6 flex flex-wrap items-center gap-1.5 py-0.5 text-[11px] px-1">
    <span class="text-slate-600 font-mono shrink-0">${connector}</span>
    <span class="w-1.5 h-1.5 rounded-full shrink-0 ${aCfg.dot}"></span>
    <span class="font-mono text-slate-600 shrink-0">${idx + 1}</span>
    <span class="text-slate-200">${textDisplay}${translationStr}</span>
    <span class="ml-auto flex items-center gap-1.5 shrink-0">
      ${durationStr ? `<span class="font-mono text-slate-500 text-[10px]">${esc(durationStr)}</span>` : ''}
      <span class="font-bold ${aCfg.cls}">${aCfg.label}</span>
      ${aTimeStr ? `<span class="font-mono text-slate-600 text-[10px]">${esc(aTimeStr)}</span>` : ''}
    </span>
  </div>`;
        }).join('');
      }

      return `
<div class="flex gap-3">
  <div class="flex flex-col items-center">
    <div class="w-7 h-7 rounded-full border-2 ${cfg.dot} flex items-center justify-center shrink-0 z-10">
      <span class="material-symbols-outlined text-sm ${cfg.iconCls}" style="font-size:14px">${esc(cfg.icon)}</span>
    </div>
    <div class="flex-1 ${connectorCls} mt-1 mb-1" style="min-height:20px"></div>
  </div>
  <div class="pb-4 min-w-0 flex-1 pt-0.5">
    <div class="flex flex-wrap items-baseline gap-1">
      <span class="text-sm font-semibold text-slate-200">${esc(p.name)}</span>
      <span class="text-[10px] font-bold uppercase tracking-wider ${cfg.iconCls}">${esc(cfg.label)}</span>
      ${timeStr}
    </div>
    ${detailStr}
    ${asrSubItems}
  </div>
</div>`;
    }).join('');
  }

  _buildAsrRecordsFlatHtml(records) {
    const statusCfg = {
      success: { cls: 'text-neon-green',    dot: 'bg-neon-green',    label: '成功' },
      empty:   { cls: 'text-accent-yellow', dot: 'bg-accent-yellow', label: '空结果' },
      error:   { cls: 'text-accent-red',    dot: 'bg-accent-red',    label: '错误' },
    };

    return records.map((r, idx) => {
      const cfg = statusCfg[r.status] || statusCfg.success;
      const durationStr = r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : '';
      const timeStr = r.start_time || '';
      const textDisplay = r.final_text
        ? `<span class="text-slate-100 font-medium">${esc(r.final_text)}</span>`
        : `<span class="text-slate-500 italic">（无识别结果）</span>`;
      const translationStr = r.translation
        ? `<span class="text-slate-400 text-[11px] ml-2">→ ${esc(r.translation)}</span>`
        : '';

      const updates = Array.isArray(r.updates) ? r.updates : [];
      const updatesHtml = updates.map((u) =>
        `<div class="flex gap-2 text-[11px]">
          <span class="font-mono text-slate-600 shrink-0 w-24">${esc(u.time || '')}</span>
          <span class="text-slate-400">${esc(u.text || '')}</span>
        </div>`
      ).join('');

      const endRow = `<div class="flex gap-2 text-[11px] mt-1">
        <span class="font-mono text-slate-600 shrink-0 w-24">${esc(r.end_time || '')}</span>
        <span class="${cfg.cls} font-bold">ASRTask ended</span>
        ${durationStr ? `<span class="text-slate-500">· ${esc(durationStr)}</span>` : ''}
        ${r.error ? `<span class="text-accent-red">· Error: ${esc(String(r.error))}</span>` : ''}
      </div>`;

      return `
<details class="rounded-lg border border-primary/10 bg-bg-dark/60 group">
  <summary class="flex flex-wrap items-center gap-2 px-3 py-2 cursor-pointer list-none select-none hover:bg-primary/5 rounded-lg transition-colors">
    <span class="w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}"></span>
    <span class="text-[10px] font-mono text-slate-600 shrink-0">${idx + 1}</span>
    ${textDisplay}${translationStr}
    <span class="ml-auto flex items-center gap-2 shrink-0">
      ${durationStr ? `<span class="text-[10px] font-mono text-slate-500">${esc(durationStr)}</span>` : ''}
      <span class="text-[10px] font-bold ${cfg.cls}">${cfg.label}</span>
      ${timeStr ? `<span class="text-[10px] font-mono text-slate-600">${esc(timeStr)}</span>` : ''}
    </span>
  </summary>
  <div class="px-3 pb-3 pt-1 space-y-0.5 border-t border-primary/10 mt-1">
    ${updatesHtml || '<p class="text-[11px] text-slate-600">无中间更新记录</p>'}
    ${endRow}
  </div>
</details>`;
    }).join('');
  }

  _buildAsrRecordsHtml(records) {
    const statusCfg = {
      success: { cls: 'text-neon-green',    dot: 'bg-neon-green',    label: '成功' },
      empty:   { cls: 'text-accent-yellow', dot: 'bg-accent-yellow', label: '空结果' },
      error:   { cls: 'text-accent-red',    dot: 'bg-accent-red',    label: '错误' },
    };

    // Group by record_id (insertion order)
    const groups = new Map();
    for (const r of records) {
      const gid = r.record_id || r.request_id;
      if (!groups.has(gid)) groups.set(gid, []);
      groups.get(gid).push(r);
    }

    const renderRecord = (r, idx) => {
      const cfg = statusCfg[r.status] || statusCfg.success;
      const durationStr = r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : '';
      const timeStr = r.start_time || '';
      const textDisplay = r.final_text
        ? `<span class="text-slate-100 font-medium">${esc(r.final_text)}</span>`
        : `<span class="text-slate-500 italic">（无识别结果）</span>`;
      const translationStr = r.translation
        ? `<span class="text-slate-400 text-[11px] ml-2">→ ${esc(r.translation)}</span>`
        : '';

      const updates = Array.isArray(r.updates) ? r.updates : [];
      const updatesHtml = updates.map((u) =>
        `<div class="flex gap-2 text-[11px]">
          <span class="font-mono text-slate-600 shrink-0 w-24">${esc(u.time || '')}</span>
          <span class="text-slate-400">${esc(u.text || '')}</span>
        </div>`
      ).join('');

      const endRow = `<div class="flex gap-2 text-[11px] mt-1">
        <span class="font-mono text-slate-600 shrink-0 w-24">${esc(r.end_time || '')}</span>
        <span class="${cfg.cls} font-bold">ASRTask ended</span>
        ${durationStr ? `<span class="text-slate-500">· ${esc(durationStr)}</span>` : ''}
        ${r.error ? `<span class="text-accent-red">· Error: ${esc(String(r.error))}</span>` : ''}
      </div>`;

      return `
<details class="rounded-lg border border-primary/10 bg-bg-dark/60 group">
  <summary class="flex flex-wrap items-center gap-2 px-3 py-2 cursor-pointer list-none select-none hover:bg-primary/5 rounded-lg transition-colors">
    <span class="w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}"></span>
    <span class="text-[10px] font-mono text-slate-600 shrink-0">${idx + 1}</span>
    ${textDisplay}${translationStr}
    <span class="ml-auto flex items-center gap-2 shrink-0">
      ${durationStr ? `<span class="text-[10px] font-mono text-slate-500">${esc(durationStr)}</span>` : ''}
      <span class="text-[10px] font-bold ${cfg.cls}">${cfg.label}</span>
      ${timeStr ? `<span class="text-[10px] font-mono text-slate-600">${esc(timeStr)}</span>` : ''}
    </span>
  </summary>
  <div class="px-3 pb-3 pt-1 space-y-0.5 border-t border-primary/10 mt-1">
    ${updatesHtml || '<p class="text-[11px] text-slate-600">无中间更新记录</p>'}
    ${endRow}
  </div>
</details>`;
    };

    let groupIdx = 0;
    const parts = [];
    for (const [gid, recs] of groups) {
      groupIdx++;
      const successCount = recs.filter(r => r.status === 'success').length;
      const errorCount   = recs.filter(r => r.status === 'error').length;
      const statusSummary = errorCount
        ? `<span class="text-accent-red text-[10px] font-bold">${errorCount} 错误</span>`
        : `<span class="text-neon-green text-[10px] font-bold">${successCount} 成功</span>`;

      const recordsHtml = recs.map((r, i) => renderRecord(r, i)).join('');

      parts.push(`
<div class="rounded-lg border border-primary/20 bg-surface/20">
  <div class="flex items-center gap-2 px-3 py-2 border-b border-primary/10">
    <span class="material-symbols-outlined text-sm text-primary/60">mic</span>
    <span class="text-[11px] font-bold text-slate-300">录音 #${groupIdx}</span>
    <span class="text-[10px] font-mono text-slate-600 truncate max-w-[200px]">${esc(gid)}</span>
    <span class="ml-auto flex items-center gap-2">${statusSummary}<span class="text-slate-600 text-[10px]">${recs.length} 句</span></span>
  </div>
  <div class="p-2 space-y-1.5">${recordsHtml}</div>
</div>`);
    }

    return parts.join('');
  }

  _buildExtractedFilesHtml(files) {
    if (!Array.isArray(files) || !files.length) return '';

    const typeBadge = (type) => {
      if (type === 'asr') {
        return `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border border-neon-purple/40 bg-neon-purple/10 text-neon-purple">ASR</span>`;
      }
      return `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary">FULL</span>`;
    };

    const items = files.map((f, i) => {
      const filePath = f.path || '';
      const fileName = f.name || filePath.split('/').pop() || 'unknown';
      const name = esc(fileName);
      const size = f.size_kb ? `${f.size_kb} KB` : '';
      const badge = typeBadge(f.type || 'full');
      const encodedPath = encodeURIComponent(filePath);
      const safePathAttr = filePath.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      return `
<details class="rounded border border-primary/10 bg-bg-dark/60" data-log-viewer="${i}" data-log-path="${safePathAttr}">
  <summary class="flex flex-wrap items-center gap-2 px-3 py-2 cursor-pointer list-none select-none hover:bg-primary/5 rounded transition-colors">
    <span class="material-symbols-outlined text-sm text-slate-500">description</span>
    <span class="text-xs text-slate-300 font-mono">${name}</span>
    ${size ? `<span class="text-[10px] text-slate-500">${esc(size)}</span>` : ''}
    ${badge}
    <a href="/api/extracted-file?path=${encodedPath}&dl=1"
       class="ml-auto text-[10px] font-bold text-primary hover:text-primary/70 flex items-center gap-1 shrink-0"
       data-log-download
       download>
      <span class="material-symbols-outlined text-sm">download</span>
      下载
    </a>
  </summary>
  <div class="px-3 pb-3 pt-1 border-t border-primary/10">
    <pre class="text-[11px] font-mono text-slate-400 overflow-x-auto whitespace-pre-wrap max-h-96 overflow-y-auto" data-log-content>加载中…</pre>
  </div>
</details>`;
    }).join('');

    return `
<div class="rounded-lg border border-primary/15 bg-surface/40 p-4">
  <p class="text-[10px] uppercase tracking-widest text-primary/50 font-bold mb-3 flex items-center gap-1.5">
    <span class="material-symbols-outlined text-sm">folder_open</span>
    提取日志（${files.length} 个文件）
  </p>
  <div class="space-y-2">${items}</div>
</div>`;
  }

  _bindLogViewers() {
    const viewers = this.el.querySelectorAll('[data-log-viewer]');
    viewers.forEach((details) => {
      const path = details.getAttribute('data-log-path');
      const pre = details.querySelector('[data-log-content]');
      if (!pre || !path) return;
      let loaded = false;
      details.addEventListener('toggle', async () => {
        if (!details.open || loaded) return;
        loaded = true;
        try {
          const resp = await fetch(`/api/extracted-file?path=${encodeURIComponent(path)}`);
          if (!resp.ok) {
            pre.textContent = `加载失败 (HTTP ${resp.status})`;
            return;
          }
          const data = await resp.json();
          pre.textContent = data.content || '（文件为空）';
        } catch (e) {
          pre.textContent = `加载失败: ${e.message}`;
        }
      });
    });
    // Prevent download link clicks from toggling the <details> parent
    this.el.querySelectorAll('[data-log-download]').forEach((a) => {
      a.addEventListener('click', (e) => e.stopPropagation());
    });
  }

  _bannerStyle() {
    const m = this._meta || {};
    const st = m.status;
    if (st === 'error' || st === 'failed') {
      return {
        banner: {
          title: '诊断失败',
          sub: '任务未正常完成，请检查日志或重试',
          icon: 'error',
          iconCls: 'text-accent-red',
        },
        bannerBorder: 'border-l-accent-red',
      };
    }
    if (m.has_failure) {
      return {
        banner: {
          title: '发现问题 / 存在警告',
          sub: '报告内包含失败或风险项，请重点查阅',
          icon: 'warning',
          iconCls: 'text-accent-yellow',
        },
        bannerBorder: 'border-l-accent-yellow',
      };
    }
    return {
      banner: {
        title: '诊断完成',
        sub: this._fromLive ? '本次会话实时生成' : '来自历史记录或分享链接',
        icon: 'check_circle',
        iconCls: 'text-neon-green',
      },
      bannerBorder: 'border-l-neon-green',
    };
  }

  _scoreValue() {
    const m = this._meta || {};
    if (typeof m.score === 'number' && !Number.isNaN(m.score)) {
      return m.score;
    }
    return parseScore(this._md || '');
  }

  _scoreBadgeHtml(score) {
    if (score == null || Number.isNaN(score)) {
      return `<span class="text-[10px] text-slate-600 font-mono">可信度 N/A</span>`;
    }
    let cls = 'text-neon-green border-neon-green/40 bg-neon-green/10';
    if (score < 5) {
      cls = 'text-accent-red border-accent-red/40 bg-accent-red/10';
    } else if (score < 7.5) {
      cls = 'text-accent-yellow border-accent-yellow/40 bg-accent-yellow/10';
    }
    return `<span class="text-xs font-mono font-bold px-2.5 py-1 rounded-md border ${cls}">可信度 ${score.toFixed(1)}/10</span>`;
  }

  _buildTocPlaceholder() {
    return '<span class="text-slate-600 text-[11px]">生成中…</span>';
  }

  onMount() {
    if (this._renderMode === 'timeline') {
      this._mountTimeline();
    } else {
      this._hydrateBody();
    }
    this._bindSharedActions();
    this._bindLogViewers();
  }

  _bindSharedActions() {
    this.on('[data-action-kb]', 'click', () => {
      document.dispatchEvent(new CustomEvent('web-diag:open-kb'));
    });
    this.on('[data-action-share]', 'click', () => this._share());
    this.on('[data-action-download]', 'click', () => this._download());
    this.on('[data-action-home]', 'click', () => {
      this.store.set('view', 'idle');
    });
  }

  _mountTimeline() {
    const body = this.$('[data-report-body]');
    if (body) highlightAll(body);
  }

  _hydrateBody() {
    const root = this.$('[data-report-body]');
    if (root) {
      highlightAll(root);
    }
    this._buildTocFromDom();
    this.el.addEventListener('click', (e) => {
      const a = e.target.closest('[data-toc-link]');
      if (!a) return;
      e.preventDefault();
      const id = a.getAttribute('data-toc-link');
      const target = id && this.el.querySelector(`#${CSS.escape(id)}`);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  _buildTocFromDom() {
    const toc = this.$('[data-report-toc]');
    const root = this.$('[data-report-body]');
    if (!toc || !root) {
      return;
    }
    const headings = root.querySelectorAll('h2, h3');
    if (!headings.length) {
      toc.innerHTML =
        '<span class="text-slate-600 text-[11px]">无标题段落</span>';
      return;
    }
    const used = new Set();
    const frag = document.createDocumentFragment();
    headings.forEach((h, i) => {
      let id = h.id || `sec-${i}`;
      if (used.has(id)) {
        id = `${id}-${i}`;
      }
      used.add(id);
      h.id = id;
      const a = document.createElement('a');
      a.href = `#${id}`;
      a.setAttribute('data-toc-link', id);
      a.className =
        'block truncate py-1 px-2 rounded text-slate-400 hover:text-primary hover:bg-primary/10 transition-colors border-l-2 border-transparent hover:border-primary/50';
      if (h.tagName === 'H3') {
        a.classList.add('pl-4', 'text-[11px]');
      }
      a.textContent = h.textContent || id;
      frag.appendChild(a);
    });
    toc.innerHTML = '';
    toc.appendChild(frag);
  }

  _share() {
    const file = this.store.get('currentHistoryFile');
    const u = new URL(location.href);
    if (file) {
      u.searchParams.set('report', file);
    }
    copyToClipboard(u.toString()).then((ok) => {
      if (ok) {
        alert('链接已复制到剪贴板');
      } else {
        prompt('复制链接', u.toString());
      }
    });
  }

  _download() {
    const raw = this._md || '';
    const name =
      (this.store.get('currentResultName') || `诊断报告_${timestamp()}`).replace(
        /[/\\:*?"<>|]/g,
        '_',
      );
    const blob = new Blob([raw], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  showResult(text, meta, fromLive) {
    this._md = text || '';
    this._meta = meta || {};
    this._fromLive = !!fromLive;
    const td = this._meta.template_data;
    this._renderMode = (td?.recordings?.length || td?.phases?.length) ? 'timeline' : 'markdown';
    this.update();
  }
}
