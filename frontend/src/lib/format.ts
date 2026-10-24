/** Compact score display: 12500 -> "12.5k". */
export function formatScore(value: number): string {
  const absolute = Math.abs(value);
  if (absolute < 1000) return String(value);
  if (absolute < 1_000_000) return `${(value / 1000).toFixed(absolute < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}m`;
}

export function formatCount(value: number, singular: string, plural?: string): string {
  const word = value === 1 ? singular : plural ?? `${singular}s`;
  return `${formatScore(value)} ${word}`;
}

export function relativeTime(timestamp: number): string {
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  if (seconds < 60) return 'just now';
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.floor(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = hours / 24;
  if (days < 30) return `${Math.floor(days)}d ago`;
  const months = days / 30;
  if (months < 12) return `${Math.floor(months)}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

/**
 * Minimal, deliberately conservative markdown-ish renderer for forum bodies.
 * Everything is escaped first, so only the patterns matched here can produce
 * markup — user and model text is never injected raw.
 */
export function renderBody(raw: string): string {
  // Link posts and tombstoned bodies are empty; emit nothing rather than a
  // stray line break that would push the actions row down.
  if (!raw || !raw.trim()) return '';

  const escaped = raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const lines = escaped.split('\n');
  const html: string[] = [];
  let inQuote = false;

  const closeQuote = () => {
    if (inQuote) {
      html.push('</blockquote>');
      inQuote = false;
    }
  };

  for (const line of lines) {
    if (line.startsWith('&gt;')) {
      if (!inQuote) {
        html.push('<blockquote>');
        inQuote = true;
      }
      html.push(`<p>${inline(line.slice(4).trim())}</p>`);
      continue;
    }
    closeQuote();
    if (!line.trim()) {
      html.push('<br/>');
      continue;
    }
    html.push(`<p>${inline(line)}</p>`);
  }
  closeQuote();
  return html.join('');
}

function inline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|\W)\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
    .replace(
      /\b(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
    )
    .replace(/\br\/([A-Za-z0-9_]{3,21})\b/g, '<a href="/r/$1">r/$1</a>')
    .replace(/\bu\/([A-Za-z0-9_-]{3,20})\b/g, '<a href="/u/$1">u/$1</a>');
}

export function pickTextColor(background: string): string {
  const hex = background.replace('#', '');
  if (hex.length !== 6) return '#ffffff';
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 140 ? '#111111' : '#ffffff';
}
