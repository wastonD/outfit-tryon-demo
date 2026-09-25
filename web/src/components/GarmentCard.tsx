import { useState } from 'react'
import { fileUrl, type Category, type Garment } from '../api'
import { useT, type TKey } from '../i18n/context'
import { StatusBadge } from './StatusBadge'
import './GarmentCard.css'

const CATEGORIES: Category[] = ['top', 'outer', 'bottom', 'skirt', 'dress', 'shoes', 'bag', 'other']

export function GarmentCard({
  garment,
  onCategoryChange,
  onDelete,
  onRetry,
  onReprocess,
  busy,
  queuePosition,
}: {
  garment: Garment
  onCategoryChange: (id: string, category: Category) => void
  onDelete: (id: string) => void
  onRetry: (garment: Garment) => void
  onReprocess: (id: string, opts: { force_segment: boolean }) => void
  busy?: boolean
  queuePosition?: number | null // 对应任务 queued 状态下的排队位置（v1.4），null/undefined 表示不在排队
}) {
  const { t } = useT()
  const [menuOpen, setMenuOpen] = useState(false)
  const img = garment.cutout ?? garment.image
  const needsCategory = garment.status === 'failed' && garment.error?.code === 'category_required'
  const canReprocess = garment.category != null && garment.status !== 'pending' && garment.status !== 'processing'
  const showQualityHint = garment.analysis?.shot === 'worn_by_model' || garment.cutout != null
  const showQueueHint = (garment.status === 'pending' || garment.status === 'processing') && queuePosition != null && queuePosition > 0

  return (
    <div className="card garment-card">
      <div className="garment-thumb">
        <img src={fileUrl(img)} alt="" />
        <div className="garment-status">
          {garment.status === 'pending' && <StatusBadge tone="pending" text={t('wardrobe.statusPending')} />}
          {garment.status === 'processing' && <StatusBadge tone="pending" text={t('wardrobe.statusProcessing')} />}
          {garment.status === 'ready' && <StatusBadge tone="ok" text={t('wardrobe.statusReady')} />}
          {garment.status === 'failed' && <StatusBadge tone="bad" text={t('wardrobe.statusFailed')} />}
        </div>
      </div>

      {showQueueHint && (
        <p className="field-hint">
          {t('common.queuedPrefix')}
          {queuePosition}
          {t('common.queuedSuffix')}
        </p>
      )}

      {garment.status === 'failed' && (
        <div className="field-error">
          {garment.error?.message}
          {!needsCategory && (
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => onRetry(garment)}>
              {t('wardrobe.retryButton')}
            </button>
          )}
        </div>
      )}

      <div className="field">
        <label>{t('wardrobe.categoryLabel')}</label>
        <select
          className="input"
          value={garment.category ?? ''}
          disabled={busy}
          onChange={(e) => onCategoryChange(garment.id, e.target.value as Category)}
        >
          {!garment.category && <option value="">{t('wardrobe.chooseCategory')}</option>}
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {t(`category.${c}` as TKey)}
            </option>
          ))}
        </select>
      </div>

      {showQualityHint && <p className="field-hint hint-quality">{t('wardrobe.poorQualityHint')}</p>}

      <div className="garment-meta">
        <span className="field-hint">{garment.source.platform ?? t('common.unknown')}</span>
        {garment.source.url && (
          <a href={garment.source.url} target="_blank" rel="noreferrer">
            {t('wardrobe.sourceLink')}
          </a>
        )}
      </div>

      <div className="garment-actions">
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy || !canReprocess}
          onClick={() => onReprocess(garment.id, { force_segment: true })}
        >
          {t('wardrobe.reprocessButton')}
        </button>
        <div className="more-menu">
          <button type="button" className="btn btn-sm" disabled={busy || !canReprocess} onClick={() => setMenuOpen((v) => !v)}>
            {t('wardrobe.moreMenu')}
          </button>
          {menuOpen && (
            <div className="more-menu-popup card">
              <button
                type="button"
                className="btn btn-sm btn-block"
                onClick={() => {
                  setMenuOpen(false)
                  onReprocess(garment.id, { force_segment: false })
                }}
              >
                {t('wardrobe.reidentifyButton')}
              </button>
            </div>
          )}
        </div>
      </div>

      <button type="button" className="btn btn-danger btn-sm btn-block" disabled={busy} onClick={() => onDelete(garment.id)}>
        {t('common.delete')}
      </button>
    </div>
  )
}
