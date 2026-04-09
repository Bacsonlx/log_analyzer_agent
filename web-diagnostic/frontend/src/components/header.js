import { Component } from '../core/component.js';

const NOTICE_DISMISSED_KEY = 'aibuds_diag_notice_dismissed';
const DOC_URL =
  'https://wiki.tuya-inc.com:7799/page/2031271880815542351';

/**
 * 顶栏：Logo、已诊断计数、文档链接、注意事项弹层、WebSocket 状态
 */
export class Header extends Component {
  render() {
    const history = this.store.get('taskHistory') || [];
    const count = Array.isArray(history) ? history.length : 0;
    const showBadge = count > 0;

    let noticeDismissed = false;
    try {
      noticeDismissed = localStorage.getItem(NOTICE_DISMISSED_KEY) === '1';
    } catch {
      /* ignore */
    }

    const ws = this.store.get('wsState') || 'disconnected';
    let dotClass = 'bg-gray-500';
    let statusText = '未连接';
    let statusTextCls = 'text-gray-400';
    if (ws === 'connected') {
      dotClass =
        'bg-neon-green shadow-[0_0_8px_rgba(0,255,157,0.6)]';
      statusText = '运行中';
      statusTextCls = 'text-neon-green';
    } else if (ws === 'error') {
      dotClass = 'bg-accent-red shadow-[0_0_8px_rgba(255,77,77,0.5)]';
      statusText = '连接错误';
      statusTextCls = 'text-accent-red';
    }

    return `
<header class="flex-shrink-0 h-14 border-b border-primary/20 bg-bg-dark/80 backdrop-blur-md flex items-center justify-between px-6 z-50 font-display">
  <div class="flex items-center gap-3">
    <span class="material-symbols-outlined text-primary text-2xl">memory</span>
    <h1 class="text-base font-bold tracking-wider uppercase text-slate-100">AIVoice</h1>
    <div class="h-4 w-px bg-primary/20 mx-1"></div>
    <span class="text-[10px] text-primary/60 uppercase tracking-widest font-medium">AI 诊断平台</span>
  </div>
  <div class="flex items-center gap-4">
    <div data-header-badge class="${showBadge ? 'flex' : 'hidden'} items-center gap-2.5 px-3 py-1 bg-primary/5 border border-primary/20 rounded-lg">
      <div class="flex items-center gap-1.5">
        <span class="material-symbols-outlined text-primary text-base">task_alt</span>
        <span class="text-[10px] text-primary/50 uppercase tracking-widest font-bold">已诊断</span>
      </div>
      <span data-header-count class="text-lg font-bold text-primary font-mono neon-glow leading-none">${count}</span>
    </div>
    <div class="h-4 w-px bg-primary/10"></div>
    <a href="${DOC_URL}" target="_blank" rel="noopener noreferrer" class="flex items-center gap-1 text-[10px] text-primary/60 hover:text-primary transition-colors uppercase tracking-widest">
      <span class="material-symbols-outlined text-sm">description</span>
      说明文档
    </a>
    <div class="relative ${noticeDismissed ? 'hidden' : ''}" data-notice-wrap>
      <button type="button" data-notice-toggle class="flex items-center gap-1 text-[10px] text-accent-yellow/80 hover:text-accent-yellow transition-colors">
        <span class="material-symbols-outlined text-base">warning</span>
        <span class="uppercase tracking-widest font-medium">注意事项</span>
      </button>
      <div data-notice-popover class="hidden absolute right-0 top-full mt-2 w-80 bg-surface border border-accent-yellow/30 rounded-lg shadow-lg shadow-accent-yellow/10 p-4 z-[100]">
        <div class="flex items-center gap-2 mb-3 pb-2 border-b border-accent-yellow/20">
          <span class="material-symbols-outlined text-accent-yellow text-lg">warning</span>
          <span class="text-accent-yellow font-bold text-xs uppercase tracking-wider">使用须知</span>
        </div>
        <ul class="space-y-2.5 text-xs text-slate-300 leading-relaxed">
          <li class="flex gap-2">
            <span class="text-primary mt-0.5 flex-shrink-0">01</span>
            <span>本工具依赖源码 AI 优化引导分析，仅支持已配置的项目。<strong class="text-accent-yellow">当前定位为 AIVoice 诊断（含设备连接与语音/AIBuds 场景）</strong>，未配置的项目请勿使用。</span>
          </li>
          <li class="flex gap-2">
            <span class="text-primary mt-0.5 flex-shrink-0">02</span>
            <span>本质由 <strong class="text-primary">Claude Code + MCP</strong> 驱动，请勿进行提示词注入攻击，后台有完整日志审计。</span>
          </li>
          <li class="flex gap-2">
            <span class="text-primary mt-0.5 flex-shrink-0">03</span>
            <span>当前为<strong class="text-accent-red">内部调试阶段</strong>，功能和性能持续优化中，请温柔对待。</span>
          </li>
        </ul>
        <button type="button" data-notice-dismiss class="mt-3 w-full py-1.5 text-[10px] text-primary/60 hover:text-primary border border-primary/20 rounded transition-colors uppercase tracking-widest">知道了</button>
      </div>
    </div>
    <div class="flex items-center gap-2">
      <span data-status-dot class="w-2 h-2 rounded-full ${dotClass}"></span>
      <span data-status-label class="text-[10px] uppercase tracking-widest ${statusTextCls}">${statusText}</span>
    </div>
  </div>
</header>`;
  }

  onMount() {
    this.on('[data-notice-toggle]', 'click', (e) => {
      e.stopPropagation();
      const p = this.$('[data-notice-popover]');
      if (!p) return;
      p.classList.toggle('hidden');
    });

    this.on('[data-notice-dismiss]', 'click', (e) => {
      e.stopPropagation();
      try {
        localStorage.setItem(NOTICE_DISMISSED_KEY, '1');
      } catch {
        /* ignore */
      }
      const wrap = this.$('[data-notice-wrap]');
      if (wrap) wrap.classList.add('hidden');
      const p = this.$('[data-notice-popover]');
      if (p) p.classList.add('hidden');
    });

    this._docClick = (e) => {
      const wrap = this.$('[data-notice-wrap]');
      const pop = this.$('[data-notice-popover]');
      if (!wrap || !pop || pop.classList.contains('hidden')) return;
      if (!wrap.contains(e.target)) pop.classList.add('hidden');
    };
    document.addEventListener('click', this._docClick);

    this.subscribe('taskHistory', () => this.update());
    this.subscribe('wsState', () => this.update());
  }

  destroy() {
    if (this._docClick) {
      document.removeEventListener('click', this._docClick);
      this._docClick = null;
    }
    super.destroy();
  }
}
