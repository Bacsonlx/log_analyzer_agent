import { Component } from '../core/component.js';
import { esc, safeFetchJson } from '../utils/helpers.js';

/**
 * 日志文件拖拽 / 点击上传，同步 store.uploadedFilePath、uploadedFileName
 */
export class FileUpload extends Component {
  render() {
    const name = this.store.get('uploadedFileName') || '';
    const path = this.store.get('uploadedFilePath') || '';
    const hasFile = Boolean(name || path);

    return `
<div class="rounded-xl border border-primary/20 bg-surface/80 p-5 neon-border">
  <input type="file" class="hidden" data-file-input accept=".log,.txt,.zip,.gz,.json" />
  <div
    data-dropzone
    class="border-2 border-dashed border-primary/30 rounded-lg py-10 px-6 text-center cursor-pointer transition-all hover:border-primary/50 hover:bg-primary/5"
  >
    <span class="material-symbols-outlined text-primary text-4xl mb-2 block">cloud_upload</span>
    <p class="text-xs text-slate-400 uppercase tracking-widest mb-1">点击或拖拽日志到此处</p>
    <p class="text-[10px] text-slate-600">支持 .log / .txt / .zip 等</p>
  </div>
  <div data-file-info class="${hasFile ? '' : 'hidden'} mt-4 flex items-start justify-between gap-3 rounded-lg bg-surface-2 border border-primary/15 px-4 py-3">
    <div class="min-w-0 flex-1">
      <p class="text-xs font-bold text-primary truncate" data-file-name>${esc(name)}</p>
      <p class="text-[10px] text-slate-500 font-mono mt-1 break-all" data-file-path>${esc(path)}</p>
    </div>
    <button type="button" data-remove-upload class="flex-shrink-0 text-slate-500 hover:text-accent-red transition-colors p-1 rounded hover:bg-accent-red/10" title="移除">
      <span class="material-symbols-outlined text-lg">close</span>
    </button>
  </div>
  <p data-upload-error class="hidden mt-2 text-[10px] text-accent-red"></p>
</div>`;
  }

  onMount() {
    const dz = this.$('[data-dropzone]');
    const input = this.$('[data-file-input]');
    this._bodyDragDepth = 0;

    this.on('[data-dropzone]', 'click', () => input?.click());

    this.on('[data-file-input]', 'change', (e) => {
      const f = e.target.files?.[0];
      if (f) this._uploadFile(f);
    });

    this.on('[data-remove-upload]', 'click', (e) => {
      e.stopPropagation();
      this._clear();
    });

    this._setDropzoneActive = (on) => {
      if (!dz) return;
      if (on) dz.classList.add('dropzone-active');
      else dz.classList.remove('dropzone-active');
    };

    this._onDragOver = (e) => {
      if (!e.dataTransfer?.types?.includes('Files')) return;
      e.preventDefault();
      this._setDropzoneActive(true);
    };
    this._onDragEnter = (e) => {
      if (!e.dataTransfer?.types?.includes('Files')) return;
      e.preventDefault();
      this._bodyDragDepth += 1;
      this._setDropzoneActive(true);
    };
    this._onDragLeave = (e) => {
      if (!e.dataTransfer?.types?.includes('Files')) return;
      e.preventDefault();
      this._bodyDragDepth = Math.max(0, this._bodyDragDepth - 1);
      if (this._bodyDragDepth === 0) this._setDropzoneActive(false);
    };
    this._onDrop = (e) => {
      e.preventDefault();
      this._bodyDragDepth = 0;
      this._setDropzoneActive(false);
      const f = e.dataTransfer?.files?.[0];
      if (f) this._uploadFile(f);
    };

    document.addEventListener('dragover', this._onDragOver);
    document.addEventListener('dragenter', this._onDragEnter);
    document.addEventListener('dragleave', this._onDragLeave);
    document.addEventListener('drop', this._onDrop);

    this.subscribe('uploadedFileName', () => this.update());
    this.subscribe('uploadedFilePath', () => this.update());
  }

  async _uploadFile(file) {
    const errEl = this.$('[data-upload-error]');
    if (errEl) {
      errEl.classList.add('hidden');
      errEl.textContent = '';
    }
    const form = new FormData();
    form.append('file', file);
    try {
      const data = await safeFetchJson('/api/upload', { method: 'POST', body: form });
      if (data.error) {
        if (errEl) {
          errEl.textContent = data.error;
          errEl.classList.remove('hidden');
        }
        return;
      }
      this.store.set('uploadedFilePath', data.path || '');
      this.store.set('uploadedFileName', data.filename || '');
    } catch (e) {
      if (errEl) {
        errEl.textContent = e.message || 'Upload failed';
        errEl.classList.remove('hidden');
      }
    }
  }

  _clear() {
    this.store.set('uploadedFilePath', '');
    this.store.set('uploadedFileName', '');
    const input = this.$('[data-file-input]');
    if (input) input.value = '';
  }

  destroy() {
    document.removeEventListener('dragover', this._onDragOver);
    document.removeEventListener('dragenter', this._onDragEnter);
    document.removeEventListener('dragleave', this._onDragLeave);
    document.removeEventListener('drop', this._onDrop);
    super.destroy();
  }
}
