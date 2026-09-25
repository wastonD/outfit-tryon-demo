import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  ApiError,
  createTurntable,
  fileUrl,
  getGarment,
  getJob,
  getOutfit,
  getStatus,
  submitFeedback,
  type Garment,
  type Job,
  type Outfit,
  type Status,
} from '../api'
import { usePoll } from '../hooks/usePoll'
import { useT, type TKey } from '../i18n/context'
import { Turntable } from '../components/Turntable'
import { Lightbox } from '../components/Lightbox'
import './LookResult.css'

const FEEDBACK_DONE_PREFIX = 'outfit.feedbackDone.'
function hasGivenFeedback(outfitId: string): boolean {
  try {
    return localStorage.getItem(FEEDBACK_DONE_PREFIX + outfitId) === '1'
  } catch {
    return false
  }
}
function markFeedbackGiven(outfitId: string) {
  try {
    localStorage.setItem(FEEDBACK_DONE_PREFIX + outfitId, '1')
  } catch {
    // 忽略（隐私模式、存储已满等）
  }
}

export default function LookResult() {
  const { id } = useParams<{ id: string }>()
  const { t } = useT()

  const [status, setStatus] = useState<Status | null>(null)
  const [garmentsById, setGarmentsById] = useState<Record<string, Garment>>({})
  const [lightbox, setLightbox] = useState<string | null>(null)
  const [ttError, setTtError] = useState<string | null>(null)
  const [ttStarting, setTtStarting] = useState(false)
  const [tick, setTick] = useState(0)

  const [feedbackRating, setFeedbackRating] = useState(0)
  const [feedbackText, setFeedbackText] = useState('')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackError, setFeedbackError] = useState<string | null>(null)
  const [feedbackDone, setFeedbackDone] = useState(false)

  useEffect(() => {
    if (id) setFeedbackDone(hasGivenFeedback(id))
  }, [id])

  async function onSubmitFeedback() {
    if (!id || (feedbackRating === 0 && !feedbackText.trim())) return
    setFeedbackSubmitting(true)
    setFeedbackError(null)
    try {
      await submitFeedback({
        target_type: 'outfit',
        target_id: id,
        rating: feedbackRating > 0 ? feedbackRating : null,
        text: feedbackText.trim() || null,
      })
      markFeedbackGiven(id)
      setFeedbackDone(true)
    } catch (e) {
      setFeedbackError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setFeedbackSubmitting(false)
    }
  }

  useEffect(() => {
    void getStatus()
      .then(setStatus)
      .catch(() => {
        // 401 等错误已经由统一处理器处理（跳转 /welcome）
      })
  }, [])

  const { data: outfit, error: outfitError } = usePoll<Outfit>(
    () => getOutfit(id!),
    (o) =>
      (o.status === 'ready' || o.status === 'failed') &&
      o.turntable.status !== 'queued' &&
      o.turntable.status !== 'running',
    2000,
    [id, tick],
  )

  const activeJobId =
    outfit && outfit.status !== 'ready' && outfit.status !== 'failed'
      ? outfit.job_id
      : outfit?.turntable.status === 'queued' || outfit?.turntable.status === 'running'
        ? outfit.turntable.job_id
        : null

  const { data: activeJob } = usePoll<Job | null>(
    () => (activeJobId ? getJob(activeJobId) : Promise.resolve(null)),
    (job) => job == null || job.status === 'succeeded' || job.status === 'failed',
    2000,
    [activeJobId],
  )

  useEffect(() => {
    if (!outfit) return
    const ids = Array.from(new Set(outfit.garment_ids))
    const missing = ids.filter((gid) => !garmentsById[gid])
    if (missing.length === 0) return
    void Promise.all(missing.map((gid) => getGarment(gid).catch(() => null))).then((list) => {
      setGarmentsById((prev) => {
        const next = { ...prev }
        for (const g of list) if (g) next[g.id] = g
        return next
      })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outfit])

  async function onGenerateTurntable() {
    if (!outfit) return
    setTtStarting(true)
    setTtError(null)
    try {
      await createTurntable(outfit.id)
      setTick((n) => n + 1)
    } catch (e) {
      setTtError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setTtStarting(false)
    }
  }

  if (outfitError) {
    return (
      <div className="container">
        <p className="field-error">{outfitError instanceof ApiError ? outfitError.message : String(outfitError)}</p>
      </div>
    )
  }

  if (!outfit) {
    return (
      <div className="container">
        <p className="field-hint">{t('common.loading')}</p>
      </div>
    )
  }

  const running = outfit.status === 'queued' || outfit.status === 'running'
  const usedGarments = outfit.garment_ids
    .filter((gid) => !outfit.result?.skipped_garment_ids.includes(gid))
    .map((gid) => garmentsById[gid])
    .filter((g): g is Garment => g != null)
  const skippedGarments = (outfit.result?.skipped_garment_ids ?? [])
    .map((gid) => garmentsById[gid])
    .filter((g): g is Garment => g != null)

  return (
    <div className="container look-result">
      <h1>{t('look.progressLabel')}</h1>

      {running && (
        <div className="card">
          {activeJob?.status === 'queued' && (activeJob.queue_position ?? 0) > 0 ? (
            <p className="field-hint">
              {t('common.queuedPrefix')}
              {activeJob.queue_position}
              {t('common.queuedSuffix')}
            </p>
          ) : (
            <>
              <div className="progress">
                <div style={{ width: `${activeJob ? (activeJob.progress.done / Math.max(1, activeJob.progress.total)) * 100 : 0}%` }} />
              </div>
              <p className="field-hint">
                {activeJob?.progress.note ?? t('common.loading')} · {t('look.progressHint')}
              </p>
            </>
          )}
        </div>
      )}

      {outfit.status === 'failed' && <div className="field-error">{outfit.error?.message ?? t('look.failed')}</div>}

      {outfit.status === 'ready' && outfit.result && (
        <>
          <div className="result-image" onClick={() => setLightbox(fileUrl(outfit.result!.image))}>
            <img src={fileUrl(outfit.result.image)} alt="" />
            <span className="badge result-badge">{t('look.aiGeneratedBadge')}</span>
            <span className="result-hint">{t('look.viewFullscreen')}</span>
          </div>

          {usedGarments.length > 0 && (
            <div className="section-title">
              <h2>{t('look.usedGarments')}</h2>
            </div>
          )}
          <div className="grid">
            {usedGarments.map((g) => (
              <div key={g.id} className="card garment-mini">
                <img src={fileUrl(g.cutout ?? g.image)} alt="" />
                {g.source.url && (
                  <a href={g.source.url} target="_blank" rel="noreferrer">
                    {t('look.goToStore')}
                  </a>
                )}
              </div>
            ))}
          </div>

          {skippedGarments.length > 0 && (
            <p className="field-hint">
              {t('look.skippedGarments')}: {skippedGarments.map((g) => t(`category.${g.category ?? 'other'}` as TKey)).join('、')}
            </p>
          )}

          <div className="section-title">
            <h2>{t('feedback.outfitTitle')}</h2>
          </div>
          <div className="card feedback-card">
            {feedbackDone ? (
              <p className="field-hint">{t('common.thanks')}</p>
            ) : (
              <>
                <div className="star-rating">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={`star ${n <= feedbackRating ? 'star-filled' : ''}`}
                      aria-label={String(n)}
                      onClick={() => setFeedbackRating(n === feedbackRating ? 0 : n)}
                    >
                      ★
                    </button>
                  ))}
                </div>
                <textarea
                  className="input"
                  rows={2}
                  placeholder={t('feedback.textPlaceholder')}
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                />
                {feedbackError && <div className="field-error">{feedbackError}</div>}
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={feedbackSubmitting || (feedbackRating === 0 && !feedbackText.trim())}
                  onClick={onSubmitFeedback}
                >
                  {feedbackSubmitting ? <span className="spinner" /> : null}
                  {feedbackSubmitting ? t('common.submitting') : t('feedback.submit')}
                </button>
              </>
            )}
          </div>

          <div className="section-title">
            <h2>{t('look.turntableTitle')}</h2>
          </div>

          {!status?.features.turntable && <p className="field-hint">{t('look.turntableComingSoon')}</p>}

          {status?.features.turntable && (
            <div className="card">
              {outfit.turntable.status === 'none' && (
                <button type="button" className="btn btn-primary" disabled={ttStarting} onClick={onGenerateTurntable}>
                  {ttStarting ? <span className="spinner" /> : null}
                  {t('look.turntableGenerate')}
                </button>
              )}
              {(outfit.turntable.status === 'queued' || outfit.turntable.status === 'running') && (
                <div>
                  {activeJob?.status === 'queued' && (activeJob.queue_position ?? 0) > 0 ? (
                    <p className="field-hint">
                      {t('common.queuedPrefix')}
                      {activeJob.queue_position}
                      {t('common.queuedSuffix')}
                    </p>
                  ) : (
                    <>
                      <div className="progress">
                        <div
                          style={{
                            width: `${activeJob ? (activeJob.progress.done / Math.max(1, activeJob.progress.total)) * 100 : 0}%`,
                          }}
                        />
                      </div>
                      <p className="field-hint">{activeJob?.progress.note ?? t('look.turntableGenerating')}</p>
                    </>
                  )}
                </div>
              )}
              {outfit.turntable.status === 'failed' && (
                <div>
                  <p className="field-error">{outfit.turntable.error?.message}</p>
                  <button type="button" className="btn" disabled={ttStarting} onClick={onGenerateTurntable}>
                    {t('common.retry')}
                  </button>
                </div>
              )}
              {outfit.turntable.status === 'ready' && outfit.turntable.video && <Turntable video={outfit.turntable.video} />}
              {ttError && <p className="field-error">{ttError}</p>}
            </div>
          )}
        </>
      )}

      {lightbox && <Lightbox src={lightbox} onClose={() => setLightbox(null)} />}
    </div>
  )
}
