/**
 * WebSocket 连接管理与消息路由
 */
export class WsClient {
  constructor(store) {
    this.store = store;
    this.ws = null;
    this._handlers = {};
    this._reconnectDelay = 1000;
    this._maxReconnect = 30000;
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(`${proto}//${location.host}/ws/chat`);

    this.ws.onopen = () => {
      this.store.set('wsState', 'connected');
      this._reconnectDelay = 1000;
    };

    this.ws.onclose = () => {
      this.store.set('wsState', 'disconnected');
      setTimeout(() => this.connect(), this._reconnectDelay);
      this._reconnectDelay = Math.min(
        this._reconnectDelay * 1.5,
        this._maxReconnect,
      );
    };

    this.ws.onerror = () => {
      this.store.set('wsState', 'error');
    };

    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        this._dispatch(msg);
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };
  }

  send(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  get isOpen() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  onMessage(type, handler) {
    (this._handlers[type] ||= []).push(handler);
  }

  _dispatch(msg) {
    const type = msg.type || 'unknown';
    (this._handlers[type] || []).forEach((fn) => fn(msg));
    (this._handlers['*'] || []).forEach((fn) => fn(msg));
  }
}
