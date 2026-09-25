export function StatusBadge({ tone, text }: { tone: 'pending' | 'ok' | 'bad' | 'neutral'; text: string }) {
  const cls = tone === 'ok' ? 'badge badge-ok' : tone === 'bad' ? 'badge badge-bad' : 'badge'
  return (
    <span className={cls}>
      {tone === 'pending' ? <span className="spinner" /> : null}
      {text}
    </span>
  )
}
