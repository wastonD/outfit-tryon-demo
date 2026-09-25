import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, deleteOutfit, fileUrl, listOutfits, type Outfit } from '../api'
import { usePoll } from '../hooks/usePoll'
import { useT } from '../i18n/context'
import { StatusBadge } from '../components/StatusBadge'
import './LookHistory.css'

export default function LookHistory() {
  const { t } = useT()
  const [tick, setTick] = useState(0)

  const { data: items, loading } = usePoll<Outfit[]>(
    () => listOutfits().then((r) => r.items),
    (list) => list.every((o) => o.status === 'ready' || o.status === 'failed'),
    2000,
    [tick],
  )

  async function onDelete(id: string, e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm(t('look.deleteConfirm'))) return
    try {
      await deleteOutfit(id)
      setTick((n) => n + 1)
    } catch (err) {
      alert(err instanceof ApiError ? err.message : String(err))
    }
  }

  return (
    <div className="container">
      <h1>{t('look.historyTitle')}</h1>

      {loading && !items && <p className="field-hint">{t('common.loading')}</p>}

      {items && items.length === 0 && <div className="empty-state">{t('look.historyEmpty')}</div>}

      {items && items.length > 0 && (
        <div className="grid">
          {items.map((o) => (
            <Link key={o.id} to={`/looks/${o.id}`} className="card look-card">
              <div className="look-thumb">
                {o.result ? (
                  <img src={fileUrl(o.result.image)} alt="" />
                ) : (
                  <div className="look-thumb-placeholder">
                    {o.status === 'failed' ? (
                      <StatusBadge tone="bad" text={t('look.failed')} />
                    ) : (
                      <StatusBadge tone="pending" text={t('wardrobe.statusProcessing')} />
                    )}
                  </div>
                )}
              </div>
              <button type="button" className="btn btn-sm btn-danger look-delete" onClick={(e) => onDelete(o.id, e)}>
                {t('common.delete')}
              </button>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
