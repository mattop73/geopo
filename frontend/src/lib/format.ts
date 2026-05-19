export function fmtPrice(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—'
  return v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

export function fmtVolume(v: number | null | undefined): string {
  if (v == null || v === 0) return '—'
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

// ISO-8601 strings without an explicit timezone designator are parsed as
// LOCAL time by `new Date(...)`, which is rarely what the backend means.
// The backend stores naive UTC timestamps, so we treat any string without a
// trailing `Z` or `±HH:MM` offset as UTC.
function parseAsUtc(s: string): Date {
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(hasTz ? s : `${s}Z`)
}

export function fmtDate(s: string | null | undefined): string {
  if (!s) return '—'
  return parseAsUtc(s).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function timeAgo(s: string | null | undefined): string {
  if (!s) return '—'
  const diff = (Date.now() - parseAsUtc(s).getTime()) / 1000
  // Clock skew or sub-second freshness — show "just now" rather than a
  // negative or zero count.
  if (diff < 5) return 'just now'
  if (diff < 60) return `${Math.round(diff)}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}
