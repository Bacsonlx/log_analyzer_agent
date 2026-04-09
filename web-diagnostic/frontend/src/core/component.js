/**
 * 轻量组件基类
 *
 * 提供 render → mount → update → destroy 生命周期，
 * 以及对 Store 的自动订阅/取消。
 */
export class Component {
  constructor(container, store) {
    this.el =
      typeof container === 'string'
        ? document.querySelector(container)
        : container;
    this.store = store;
    this._unsubs = [];
    this._mounted = false;
  }

  render() {
    return '';
  }

  mount() {
    this.el.innerHTML = this.render();
    this._mounted = true;
    this.onMount();
  }

  update() {
    if (!this._mounted) return;
    this.el.innerHTML = this.render();
    this.onMount();
  }

  onMount() {}

  subscribe(key, callback) {
    const unsub = this.store.on(key, callback);
    this._unsubs.push(unsub);
  }

  $(selector) {
    return this.el.querySelector(selector);
  }

  $$(selector) {
    return this.el.querySelectorAll(selector);
  }

  on(selector, event, handler) {
    const el = this.$(selector);
    if (el) el.addEventListener(event, handler);
  }

  destroy() {
    this._unsubs.forEach((fn) => fn());
    this._unsubs = [];
    this._mounted = false;
    this.el.innerHTML = '';
  }
}
