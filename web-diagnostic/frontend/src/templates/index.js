/**
 * 诊断报告模版定义
 * 每个模版对应一种场景的标准排查流程，phases 来源于知识库 phases 字段
 */
export const TEMPLATES = {
  'audio-recognition': {
    label: '实时链路',
    phases: ['选择设备', '选择语言', '点击开始', '开始识别', '识别结束'],
  },
  'offline-transcription': {
    label: '离线转写/总结',
    phases: ['触发转写', '收到转写MQ', '转写结果写入', '触发总结', '收到总结MQ', '总结结果写入'],
  },
  recording: {
    label: '录音问题',
    phases: ['录音入口', '任务初始化', '音频源选择', '录音进行中', '录音结束'],
  },
  'cloud-upload': {
    label: '云同步上传',
    phases: ['发起上传', '获取加密密钥', '文件加密', '文件上传', 'DB状态更新'],
  },
};

/**
 * @param {string} id  模版 ID
 * @returns {{ label: string, phases: string[] } | null}
 */
export function getTemplateMeta(id) {
  if (!id) return null;
  if (id === 'translation') {
    return TEMPLATES['audio-recognition'] || null;
  }
  return TEMPLATES[id] || null;
}
