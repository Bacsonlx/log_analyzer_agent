export function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

export function escAttr(s) {
  return s
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/\n/g, '\\n');
}

export async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return fallbackCopy(text);
    }
  }
  return fallbackCopy(text);
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {}
  document.body.removeChild(ta);
  return ok;
}

export function formatDuration(ms) {
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatToolName(name) {
  return name
    .replace('mcp__log-analyzer__', '')
    .replace('mcp__protocol-kb__', '')
    .replace(/_/g, ' ');
}

export function parseScore(text) {
  const m = text.match(/\[诊断可信度:\s*([\d.]+)\s*\/\s*10\s*\]/);
  return m ? parseFloat(m[1]) : null;
}

export function stripScoreLine(text) {
  return text
    .replace(/\n*\[诊断可信度:\s*[\d.]+\s*\/\s*10\s*\]\s*$/, '')
    .trim();
}

export function timestamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
}

/**
 * 安全 fetch：非 2xx 时抛出带状态码和响应体摘要的错误，
 * 避免对非 JSON 响应直接调用 res.json() 导致解析失败。
 */
export async function safeFetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`请求失败 (${res.status}): ${text.slice(0, 200)}`);
  }
  return res.json();
}
