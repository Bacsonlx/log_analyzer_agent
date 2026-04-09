import { Component } from '../core/component.js';
import { Report } from '../components/report.js';
import { KbModal } from '../components/kb-modal.js';

let kbModalSingleton = null;

/**
 * 知识库归纳抽屉单例（挂到 body）
 */
export function getKbModal(store) {
  if (!kbModalSingleton) {
    const host = document.createElement('div');
    document.body.appendChild(host);
    kbModalSingleton = new KbModal(host, store);
    kbModalSingleton.mount();
  }
  return kbModalSingleton;
}

/**
 * 结果页：居中 Report；KbModal 通过 getKbModal 使用
 */
export class ResultView extends Component {
  constructor(container, store) {
    super(container, store);
    this._report = null;
  }

  render() {
    return `
<div class="h-full min-h-0 overflow-y-auto cyber-grid flex justify-center px-4 py-6">
  <div class="w-full max-w-5xl flex flex-col min-h-0" data-report-slot></div>
</div>`;
  }

  onMount() {
    // 知识库抽屉挂到 document.body（单例），保证结果页可接收 WS knowledge_* 推送
    getKbModal(this.store);

    const slot = this.$('[data-report-slot]');
    if (slot) {
      this._report = new Report(slot, this.store);
      this._report.mount();
    }

    const md = this.store.get('currentResultMd') || '';
    const meta = this.store.get('resultMeta') || {};
    const fromLive = !!this.store.get('resultFromLive');
    this._report?.showResult(md, meta, fromLive);
  }

  destroy() {
    this._report?.destroy();
    this._report = null;
    super.destroy();
  }
}
