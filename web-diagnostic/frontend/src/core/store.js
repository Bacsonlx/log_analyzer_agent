/**
 * 极简状态管理（发布-订阅）
 */
export class Store {
  constructor(initial = {}) {
    this.state = { ...initial };
    this._listeners = {};
  }

  get(key) {
    return this.state[key];
  }

  set(key, value) {
    const prev = this.state[key];
    this.state[key] = value;
    if (prev !== value) {
      (this._listeners[key] || []).forEach((fn) => fn(value, prev));
      (this._listeners['*'] || []).forEach((fn) => fn(key, value, prev));
    }
  }

  on(key, fn) {
    (this._listeners[key] ||= []).push(fn);
    return () => {
      this._listeners[key] = this._listeners[key].filter((f) => f !== fn);
    };
  }

  batch(updates) {
    Object.entries(updates).forEach(([k, v]) => {
      this.state[k] = v;
    });
    Object.entries(updates).forEach(([k, v]) => {
      (this._listeners[k] || []).forEach((fn) => fn(v));
    });
    (this._listeners['*'] || []).forEach((fn) => fn('batch', updates));
  }
}

export function createStore() {
  return new Store({
    view: 'idle',
    wsState: 'disconnected',
    webSessionId: '',
    ssoVerified: false,
    logMode: 'auto',
    oauthEnabled: false,

    uploadedFilePath: '',
    uploadedFileName: '',

    taskQueue: [],
    taskHistory: [],
    taskAction: null,
    ssoWarning: '',
    taskIdCounter: 0,
    activeServerTaskId: '',

    analysisStartTime: 0,
    eventCount: 0,
    steps: [],
    progress: 0,
    assistantText: '',

    currentResultMd: '',
    currentResultName: '',
    currentHistoryFile: '',
    resultMeta: {},

    analysisTaskTitle: '',
    analysisTaskFile: '',
    activeTaskTitle: '',
    activeTaskFile: '',
    needSsoHint: '',
    resultFromLive: false,

    /** 应用入口设置 WsClient，供 KbModal 发送 knowledge */
    wsClient: null,
  });
}
