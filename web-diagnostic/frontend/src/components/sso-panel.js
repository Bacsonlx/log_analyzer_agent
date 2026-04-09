import { Component } from '../core/component.js';
import { esc, safeFetchJson } from '../utils/helpers.js';

/**
 * SSO 校验区：OAuth、Cookie / Token、校验接口；已通过时可折叠为一行状态
 */
export class SsoPanel extends Component {
  constructor(container, store) {
    super(container, store);
    this._ssoExpanded = false;
    this._verifyMessage = '';
    this._verifyError = false;
    this._warnHint = false;
  }

  render() {
    const verified = !!this.store.get('ssoVerified');
    const oauthEnabled = !!this.store.get('oauthEnabled');
    const webSessionId = this.store.get('webSessionId') || '';

    if (verified && !this._ssoExpanded) {
      return `
<div class="rounded-xl border border-neon-green/30 bg-surface/80 p-4 neon-border">
  <button type="button" data-sso-expand-toggle class="w-full flex items-center justify-between gap-3 text-left group">
    <div class="flex items-center gap-2 min-w-0">
      <span class="material-symbols-outlined text-neon-green text-xl flex-shrink-0">verified</span>
      <span class="text-xs text-neon-green font-medium truncate">已通过校验，自动下载将使用当前登录态</span>
    </div>
    <span class="material-symbols-outlined text-neon-green/60 text-lg group-hover:text-neon-green transition-colors flex-shrink-0">expand_more</span>
  </button>
</div>`;
    }

    const statusLine = !webSessionId
      ? '<span class="text-[10px] text-slate-500">正在等待 WebSocket 会话…</span>'
      : verified
        ? '<span class="text-[10px] text-neon-green">校验已通过，可发起自动下载诊断。</span>'
        : '<span class="text-[10px] text-accent-yellow/90">请完成 Cookie / Token 校验后使用自动下载。</span>';

    const msg = this._verifyMessage;
    let msgCls = 'text-primary/80';
    if (this._verifyError) {
      msgCls = 'text-accent-red';
    } else if (this._warnHint && msg) {
      msgCls = 'text-accent-yellow/90';
    }

    return `
<div class="rounded-xl border border-primary/20 bg-surface/80 p-4 space-y-3 neon-border">
  ${verified ? `
  <button type="button" data-sso-collapse-toggle class="flex items-center gap-2 text-[10px] text-neon-green/80 hover:text-neon-green uppercase tracking-widest">
    <span class="material-symbols-outlined text-base">expand_less</span>
    收起校验面板
  </button>` : ''}
  <div class="flex flex-wrap items-center gap-2">
    ${oauthEnabled ? `
    <button type="button" data-oauth-start class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-neon-purple/15 border border-neon-purple/40 text-[10px] font-bold uppercase tracking-wider text-neon-purple hover:bg-neon-purple/25 transition-colors disabled:opacity-40 disabled:pointer-events-none" ${!webSessionId ? 'disabled' : ''}>
      <span class="material-symbols-outlined text-sm">key</span>
      一键 OAuth 登录
    </button>` : ''}
  </div>
  <div>
    <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">Cookie（含 SSO_USER_TOKEN）</label>
    <textarea data-sso-cookie rows="3" class="w-full text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-600 focus:border-primary/50 focus:ring-0" placeholder="粘贴浏览器 Cookie 字符串…"></textarea>
  </div>
  <div>
    <label class="block text-[10px] text-primary/50 uppercase tracking-widest mb-1">SSO_USER_TOKEN</label>
    <input type="password" data-sso-token class="w-full text-xs bg-bg-dark border border-primary/20 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-600 focus:border-primary/50 focus:ring-0" placeholder="或直接粘贴 Token" autocomplete="off" />
  </div>
  <div class="flex flex-wrap items-center gap-3">
    <button type="button" data-sso-verify class="px-4 py-2 rounded-lg bg-primary/20 border border-primary/40 text-xs font-bold uppercase tracking-wider text-primary hover:bg-primary/30 transition-colors disabled:opacity-40 disabled:pointer-events-none">
      验证
    </button>
    ${statusLine}
  </div>
  ${msg ? `<p data-sso-msg class="text-[10px] ${msgCls}">${esc(msg)}</p>` : '<p data-sso-msg class="hidden text-[10px]"></p>'}
</div>`;
  }

  onMount() {
    this.on('[data-sso-expand-toggle]', 'click', () => {
      this._ssoExpanded = true;
      this.update();
    });

    this.on('[data-sso-collapse-toggle]', 'click', () => {
      this._ssoExpanded = false;
      this.update();
    });

    this.on('[data-sso-verify]', 'click', () => this._verify());

    this.on('[data-oauth-start]', 'click', () => {
      const wid = this.store.get('webSessionId') || '';
      if (!wid) {
        return;
      }
      window.location.href = `/api/oauth/app-log/start?web_session_id=${encodeURIComponent(wid)}`;
    });

    if (!this._ssoStoreBound) {
      this._ssoStoreBound = true;
      this.subscribe('ssoVerified', () => {
        if (this.store.get('ssoVerified')) {
          this._verifyMessage = '';
          this._verifyError = false;
          this._warnHint = false;
          this._ssoExpanded = false;
        }
        this.update();
      });
      this.subscribe('webSessionId', () => this.update());
      this.subscribe('oauthEnabled', () => this.update());
    }
  }

  destroy() {
    this._ssoStoreBound = false;
    super.destroy();
  }

  async _verify() {
    const cookieRaw = this.$('[data-sso-cookie]')?.value?.trim() || '';
    const tokRaw = this.$('[data-sso-token]')?.value?.trim() || '';
    const webSessionId = this.store.get('webSessionId') || '';

    if (!cookieRaw && !tokRaw) {
      this._verifyMessage = '请填写 Cookie 或 SSO_USER_TOKEN';
      this._verifyError = true;
      this.update();
      return;
    }
    if (!webSessionId) {
      this._verifyMessage = 'WebSocket 未就绪，请稍后重试';
      this._verifyError = true;
      this.update();
      return;
    }

    const btn = this.$('[data-sso-verify]');
    if (btn) btn.disabled = true;
    this._verifyMessage = '正在验证…';
    this._verifyError = false;
    this.update();

    try {
      const body = { web_session_id: webSessionId };
      if (cookieRaw) body.cookie = cookieRaw;
      else body.token = tokRaw;

      const data = await safeFetchJson('/api/sso-verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (data.ok) {
        this.store.set('ssoVerified', true);
        const c = this.$('[data-sso-cookie]');
        const t = this.$('[data-sso-token]');
        if (c) c.value = '';
        if (t) t.value = '';
        this._verifyMessage = '验证成功';
        this._verifyError = false;
        this._ssoExpanded = false;
      } else {
        this._verifyMessage = data.error || '验证失败';
        this._verifyError = true;
      }
    } catch (e) {
      this._verifyMessage = e.message || '请求失败';
      this._verifyError = true;
    } finally {
      if (btn) btn.disabled = false;
      this.update();
    }
  }

  /**
   * 自动下载被拒：展开面板并提示用户完成登录态
   */
  showNeedSsoHint(hint) {
    this._ssoExpanded = true;
    this._verifyMessage =
      hint ||
      '自动下载需要先完成日志平台登录态验证（Cookie / Token 或 OAuth）。';
    this._verifyError = false;
    this._warnHint = true;
    this.update();
    this.el?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }
}
