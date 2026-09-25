import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  deleteGarment,
  getJob,
  importImagesFiles,
  importImagesJson,
  importLink,
  listGarments,
  patchGarment,
  reprocessGarment,
  retryJob,
  type Category,
  type Garment,
  type Job,
} from '../api'
import { usePoll } from '../hooks/usePoll'
import { useT, type TKey } from '../i18n/context'
import { GarmentCard } from '../components/GarmentCard'
import './Wardrobe.css'

const FILTERS: Array<Category | 'all'> = ['all', 'top', 'outer', 'bottom', 'skirt', 'dress', 'shoes', 'bag', 'other']

// 部分浏览器/系统对 avif、heic 文件报告的 MIME 类型为空，因此额外用扩展名兜底，避免被误拦截。
function isImageFile(file: File): boolean {
  return file.type.startsWith('image/') || /\.(avif|heic)$/i.test(file.name)
}

type Candidates = {
  images: string[]
  product: { url: string | null; platform: string | null; title: string | null; price: string | null }
}

export default function Wardrobe() {
  const { t } = useT()

  const [linkText, setLinkText] = useState('')
  const [importingLink, setImportingLink] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)
  const [linkErrorHint, setLinkErrorHint] = useState(false)
  const [candidates, setCandidates] = useState<Candidates | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [addingSelected, setAddingSelected] = useState(false)

  const [filter, setFilter] = useState<Category | 'all'>('all')
  const [tick, setTick] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())
  const fileInputRef = useRef<HTMLInputElement>(null)

  const refetch = () => setTick((n) => n + 1)

  const { data: items, loading } = usePoll<Garment[]>(
    () => listGarments(filter === 'all' ? undefined : { category: filter }).then((r) => r.items),
    (list) => list.every((g) => g.status === 'ready' || g.status === 'failed'),
    2000,
    [filter, tick],
  )

  // 衣物卡片要显示排队位置（v1.4），需要额外拉取还在处理中的衣物对应的任务。
  const pendingJobIds = useMemo(() => {
    const ids = (items ?? [])
      .filter((g) => g.status === 'pending' || g.status === 'processing')
      .map((g) => g.job_id)
      .filter((id): id is string => id != null)
    return Array.from(new Set(ids))
  }, [items])

  const { data: pendingJobs } = usePoll<Job[]>(
    () =>
      pendingJobIds.length === 0
        ? Promise.resolve([])
        : Promise.all(pendingJobIds.map((id) => getJob(id).catch(() => null))).then((list) => list.filter((j): j is Job => j != null)),
    (list) => list.every((j) => j.status === 'succeeded' || j.status === 'failed'),
    2000,
    [pendingJobIds.join('|')],
  )

  const queuePositionByGarmentId = useMemo(() => {
    const map: Record<string, number | null> = {}
    for (const job of pendingJobs ?? []) {
      map[job.target_id] = job.status === 'queued' ? job.queue_position : null
    }
    return map
  }, [pendingJobs])

  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.items ?? [])
        .filter((item) => item.kind === 'file')
        .map((item) => item.getAsFile())
        .filter((f): f is File => f != null && isImageFile(f))
      if (files.length > 0) void handleFiles(files)
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleFiles(files: File[]) {
    try {
      await importImagesFiles(files, {})
      refetch()
    } catch (e) {
      setLinkError(e instanceof ApiError ? e.message : String(e))
    }
  }

  async function submitLink() {
    setLinkError(null)
    setLinkErrorHint(false)
    setCandidates(null)
    if (!linkText.trim()) return
    setImportingLink(true)
    try {
      const res = await importLink(linkText.trim())
      setCandidates({ images: res.product.images, product: res.product })
      setSelected(new Set(res.product.images))
    } catch (e) {
      if (e instanceof ApiError) {
        setLinkError(e.message)
        setLinkErrorHint(e.code === 'resolve_failed')
      } else {
        setLinkError(String(e))
      }
    } finally {
      setImportingLink(false)
    }
  }

  function toggleCandidate(url: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  async function addSelectedCandidates() {
    if (!candidates || selected.size === 0) return
    setAddingSelected(true)
    try {
      await importImagesJson({
        images: Array.from(selected).map((url) => ({ url })),
        source: {
          url: candidates.product.url ?? undefined,
          title: candidates.product.title ?? undefined,
          platform: candidates.product.platform ?? undefined,
          price: candidates.product.price ?? undefined,
        },
      })
      setCandidates(null)
      setLinkText('')
      refetch()
    } catch (e) {
      setLinkError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setAddingSelected(false)
    }
  }

  async function withBusy(id: string, fn: () => Promise<void>) {
    setBusyIds((prev) => new Set(prev).add(id))
    try {
      await fn()
    } finally {
      setBusyIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  async function onCategoryChange(id: string, category: Category) {
    await withBusy(id, async () => {
      await patchGarment(id, category)
      refetch()
    })
  }

  async function onDelete(id: string) {
    if (!confirm(t('wardrobe.deleteConfirm'))) return
    await withBusy(id, async () => {
      await deleteGarment(id)
      refetch()
    })
  }

  async function onRetry(g: Garment) {
    if (!g.job_id) return
    await withBusy(g.id, async () => {
      await retryJob(g.job_id!)
      refetch()
    })
  }

  async function onReprocess(id: string, opts: { force_segment: boolean }) {
    await withBusy(id, async () => {
      try {
        await reprocessGarment(id, opts)
        refetch()
      } catch (e) {
        if (!(e instanceof ApiError && e.code === 'garment_busy')) throw e
      }
    })
  }

  return (
    <div className="container">
      <h1>{t('wardrobe.title')}</h1>

      <div className="card import-area">
        <div className="field">
          <label>{t('wardrobe.importLinkPlaceholder')}</label>
          <div className="import-link-row">
            <input
              className="input"
              value={linkText}
              placeholder={t('wardrobe.importLinkPlaceholder')}
              disabled={importingLink}
              onChange={(e) => setLinkText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submitLink()}
            />
            <button type="button" className="btn btn-primary" disabled={importingLink || !linkText.trim()} onClick={submitLink}>
              {importingLink ? <span className="spinner" /> : null}
              {t('wardrobe.importLinkButton')}
            </button>
          </div>
          {linkError && (
            <div className="field-error">
              {linkError}
              {linkErrorHint && <div className="field-hint">{t('wardrobe.browserExtHint')}</div>}
            </div>
          )}
        </div>

        {candidates && (
          <div className="candidates">
            <div className="section-title">
              <h3>{t('wardrobe.candidatesTitle')}</h3>
            </div>
            <div className="grid">
              {candidates.images.map((url) => (
                <label key={url} className={`candidate ${selected.has(url) ? 'selected' : ''}`}>
                  <input type="checkbox" checked={selected.has(url)} onChange={() => toggleCandidate(url)} />
                  <img src={url} alt="" />
                </label>
              ))}
            </div>
            <button
              type="button"
              className="btn btn-primary"
              disabled={addingSelected || selected.size === 0}
              onClick={addSelectedCandidates}
            >
              {addingSelected ? <span className="spinner" /> : null}
              {t('wardrobe.addSelected')} ({selected.size})
            </button>
          </div>
        )}

        <div
          className={`dropzone ${dragOver ? 'dragover' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            const files = Array.from(e.dataTransfer.files).filter(isImageFile)
            if (files.length > 0) void handleFiles(files)
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <p>{t('wardrobe.dropHint')}</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.avif,.heic,image/avif,image/heic"
            multiple
            hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? [])
              if (files.length > 0) void handleFiles(files)
              e.target.value = ''
            }}
          />
        </div>
      </div>

      <div className="section-title">
        <h2>{t('wardrobe.title')}</h2>
        <select className="input filter-select" value={filter} onChange={(e) => setFilter(e.target.value as Category | 'all')}>
          {FILTERS.map((f) => (
            <option key={f} value={f}>
              {f === 'all' ? t('wardrobe.filterAll') : t(`category.${f}` as TKey)}
            </option>
          ))}
        </select>
      </div>

      {loading && !items && <p className="field-hint">{t('common.loading')}</p>}

      {items && items.length === 0 && <div className="empty-state">{t('wardrobe.dropHintEmpty')}</div>}

      {items && items.length > 0 && (
        <div className="grid">
          {items.map((g) => (
            <GarmentCard
              key={g.id}
              garment={g}
              busy={busyIds.has(g.id)}
              queuePosition={queuePositionByGarmentId[g.id]}
              onCategoryChange={onCategoryChange}
              onDelete={onDelete}
              onRetry={onRetry}
              onReprocess={onReprocess}
            />
          ))}
        </div>
      )}
    </div>
  )
}
