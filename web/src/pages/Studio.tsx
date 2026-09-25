import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ApiError,
  createOutfit,
  fileUrl,
  getPresets,
  getStatus,
  listGarments,
  type Garment,
  type OutfitOptions,
  type Preset,
  type Status,
} from '../api'
import { useAuth } from '../auth/context'
import { useT } from '../i18n/context'
import './Studio.css'

const HEIGHT_ORDER: Preset['body']['height'][] = ['short', 'medium', 'tall']
const BUILD_ORDER: Preset['body']['build'][] = ['slim', 'regular', 'plus']
const SKIN_ORDER: Preset['body']['skin'][] = ['light', 'medium', 'dark']

type SlotKey = 'top' | 'outer' | 'bottom' | 'dress'

function nearestPreset(presets: Preset[], gender: 'female' | 'male', h: number, b: number, s: number): Preset | null {
  const pool = presets.filter((p) => p.body.gender === gender)
  const candidates = pool.length > 0 ? pool : presets
  let best: Preset | null = null
  let bestDist = Infinity
  for (const p of candidates) {
    const dist =
      Math.abs(HEIGHT_ORDER.indexOf(p.body.height) - h) +
      Math.abs(BUILD_ORDER.indexOf(p.body.build) - b) +
      Math.abs(SKIN_ORDER.indexOf(p.body.skin) - s)
    if (dist < bestDist) {
      bestDist = dist
      best = p
    }
  }
  return best
}

function bodyKeyOf(body: Preset['body']): string {
  return `${body.gender}-${body.height}-${body.build}-${body.skin}`
}

function sameBody(a: Preset['body'], b: Preset['body']): boolean {
  return a.gender === b.gender && a.height === b.height && a.build === b.build && a.skin === b.skin
}

// 同一体型选过的形象记在 localStorage 里，换一次体型再换回来时还能记住上次选的那张。
const PRESET_CHOICE_PREFIX = 'outfit.presetChoice.'
function getStoredPresetChoice(bodyKey: string): string | null {
  try {
    return localStorage.getItem(PRESET_CHOICE_PREFIX + bodyKey)
  } catch {
    return null
  }
}
function setStoredPresetChoice(bodyKey: string, presetId: string) {
  try {
    localStorage.setItem(PRESET_CHOICE_PREFIX + bodyKey, presetId)
  } catch {
    // 忽略（隐私模式、存储已满等）
  }
}

export default function Studio() {
  const { t } = useT()
  const navigate = useNavigate()
  const auth = useAuth()

  const [presets, setPresets] = useState<Preset[]>([])
  const [status, setStatus] = useState<Status | null>(null)
  const [garments, setGarments] = useState<Garment[]>([])
  const [loading, setLoading] = useState(true)

  const [gender, setGender] = useState<'female' | 'male'>('female')
  const [heightIdx, setHeightIdx] = useState(1)
  const [buildIdx, setBuildIdx] = useState(1)
  const [skinIdx, setSkinIdx] = useState(0)

  const [slots, setSlots] = useState<Record<SlotKey, string | null>>({ top: null, outer: null, bottom: null, dress: null })
  const [openSlot, setOpenSlot] = useState<SlotKey | null>(null)
  const [tuck, setTuck] = useState<OutfitOptions['tuck']>('auto')
  const [upscale, setUpscale] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const [p, s, g] = await Promise.all([getPresets(), getStatus(), listGarments()])
        setPresets(p.items)
        setStatus(s)
        setGarments(g.items.filter((item) => item.status === 'ready'))
      } catch {
        // 401 等错误已经由统一处理器处理（跳转 /welcome）
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  // defaultPreset：按体型滑块找到的最接近体型（同一体型下永远是推荐顺序里排第一的那个）。
  const defaultPreset = useMemo(
    () => nearestPreset(presets, gender, heightIdx, buildIdx, skinIdx),
    [presets, gender, heightIdx, buildIdx, skinIdx],
  )

  // presetFamily：和 defaultPreset 同一个 body 组合的所有候选形象（v1.4：一个体型可以有多个形象）。
  const presetFamily = useMemo(
    () => (defaultPreset ? presets.filter((p) => sameBody(p.body, defaultPreset.body)) : []),
    [presets, defaultPreset],
  )
  const bodyKey = defaultPreset ? bodyKeyOf(defaultPreset.body) : null

  // preset：presetFamily 里当前展示的那一个，默认是 defaultPreset，除非 localStorage 记了别的选择。
  const [preset, setPreset] = useState<Preset | null>(null)

  useEffect(() => {
    if (presetFamily.length === 0) {
      setPreset(defaultPreset)
      return
    }
    const stored = bodyKey ? getStoredPresetChoice(bodyKey) : null
    const found = stored ? presetFamily.find((p) => p.id === stored) : undefined
    setPreset(found ?? presetFamily[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bodyKey, presetFamily])

  const presetIndex = preset ? presetFamily.findIndex((p) => p.id === preset.id) : -1

  function cycleLook() {
    if (!bodyKey || presetFamily.length <= 1) return
    const nextIndex = (presetIndex + 1) % presetFamily.length
    const next = presetFamily[nextIndex]
    setPreset(next)
    setStoredPresetChoice(bodyKey, next.id)
  }

  const showMoreHint =
    presets.length <= 1 ||
    (defaultPreset != null &&
      (defaultPreset.body.gender !== gender ||
        HEIGHT_ORDER.indexOf(defaultPreset.body.height) !== heightIdx ||
        BUILD_ORDER.indexOf(defaultPreset.body.build) !== buildIdx ||
        SKIN_ORDER.indexOf(defaultPreset.body.skin) !== skinIdx))

  function eligibleFor(slot: SlotKey): Garment[] {
    if (slot === 'bottom') return garments.filter((g) => g.category === 'bottom' || g.category === 'skirt')
    if (slot === 'dress') return garments.filter((g) => g.category === 'dress')
    return garments.filter((g) => g.category === slot)
  }

  function garmentById(id: string | null): Garment | undefined {
    if (!id) return undefined
    return garments.find((g) => g.id === id)
  }

  function pickSlot(slot: SlotKey, garmentId: string) {
    setSlots((prev) => ({ ...prev, [slot]: garmentId }))
    setOpenSlot(null)
  }

  const hasDress = slots.dress != null
  const garmentIds = hasDress
    ? [slots.dress, slots.outer].filter((id): id is string => id != null)
    : [slots.top, slots.outer, slots.bottom].filter((id): id is string => id != null)
  const showLayeringHint = slots.outer != null && (slots.top != null || slots.dress != null)

  async function onGenerate() {
    if (!preset || garmentIds.length === 0) return
    setGenerating(true)
    setError(null)
    try {
      const outfit = await createOutfit({ preset_id: preset.id, garment_ids: garmentIds, options: { tuck, upscale } })
      void auth.refresh().catch(() => {
        // 忽略：只是为了让下次回到搭配台时额度显示是最新的，刷新失败不影响本次生成
      })
      navigate(`/looks/${outfit.id}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setGenerating(false)
    }
  }

  function renderSlot(slot: SlotKey, labelKey: 'studio.slotTop' | 'studio.slotOuter' | 'studio.slotBottom' | 'studio.slotDress', disabled: boolean) {
    const g = garmentById(slots[slot])
    const options = eligibleFor(slot)
    return (
      <div className={`slot ${disabled ? 'slot-disabled' : ''}`}>
        <div className="slot-label">{t(labelKey)}</div>
        <button
          type="button"
          className="slot-box"
          disabled={disabled}
          onClick={() => setOpenSlot(openSlot === slot ? null : slot)}
        >
          {g ? <img src={fileUrl(g.cutout ?? g.image)} alt="" /> : <span className="field-hint">{t('studio.chooseGarment')}</span>}
        </button>
        {openSlot === slot && (
          <div className="slot-picker card">
            {options.length === 0 && <p className="field-hint">{t('common.empty')}</p>}
            <div className="grid">
              {options.map((opt) => (
                <button type="button" key={opt.id} className="slot-option" onClick={() => pickSlot(slot, opt.id)}>
                  <img src={fileUrl(opt.cutout ?? opt.image)} alt="" />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  if (loading) return <div className="container"><p className="field-hint">{t('common.loading')}</p></div>

  return (
    <div className="container">
      <h1>{t('studio.title')}</h1>

      <div className="studio-layout">
        <div className="card model-picker">
          <div className="gender-toggle">
            <button type="button" className={`btn ${gender === 'female' ? 'btn-primary' : ''}`} onClick={() => setGender('female')}>
              {t('studio.genderFemale')}
            </button>
            <button type="button" className={`btn ${gender === 'male' ? 'btn-primary' : ''}`} onClick={() => setGender('male')}>
              {t('studio.genderMale')}
            </button>
          </div>

          {preset && (
            <div className="model-preview">
              <img src={fileUrl(preset.image)} alt="" />
              {preset.internal_only && <span className="badge">{t('studio.internalOnlyBadge')}</span>}
              <span className="badge ai-model-badge">{t('studio.aiModelBadge')}</span>
            </div>
          )}
          {presetFamily.length > 1 && (
            <button type="button" className="btn btn-sm btn-block change-look-btn" onClick={cycleLook}>
              {t('studio.changeLook')} ({presetIndex + 1}/{presetFamily.length})
            </button>
          )}

          <div className="field">
            <label>{t('studio.height')}</label>
            <input type="range" min={0} max={2} value={heightIdx} onChange={(e) => setHeightIdx(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>{t('studio.build')}</label>
            <input type="range" min={0} max={2} value={buildIdx} onChange={(e) => setBuildIdx(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>{t('studio.skin')}</label>
            <input type="range" min={0} max={2} value={skinIdx} onChange={(e) => setSkinIdx(Number(e.target.value))} />
          </div>

          {showMoreHint && <p className="field-hint">{t('studio.moreComingSoon')}</p>}
        </div>

        <div className="card slots-panel">
          <div className="slots">
            {renderSlot('top', 'studio.slotTop', hasDress)}
            {renderSlot('outer', 'studio.slotOuter', false)}
            {renderSlot('bottom', 'studio.slotBottom', hasDress)}
            {renderSlot('dress', 'studio.slotDress', false)}
          </div>
          {hasDress && <p className="field-hint">{t('studio.dressReplacesHint')}</p>}

          <div className="field">
            <label>{t('studio.tuckLabel')}</label>
            <div className="tuck-toggle">
              {(['auto', 'in', 'out'] as const).map((opt) => (
                <button
                  type="button"
                  key={opt}
                  className={`btn btn-sm ${tuck === opt ? 'btn-primary' : ''}`}
                  onClick={() => setTuck(opt)}
                >
                  {t(opt === 'auto' ? 'studio.tuckAuto' : opt === 'in' ? 'studio.tuckIn' : 'studio.tuckOut')}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label>
              <input
                type="checkbox"
                checked={upscale}
                disabled={!status?.features.upscale}
                onChange={(e) => setUpscale(e.target.checked)}
              />{' '}
              {t('studio.upscaleLabel')}
            </label>
            {!status?.features.upscale && <div className="field-hint">{t('studio.upscaleDisabledHint')}</div>}
          </div>

          {showLayeringHint && <p className="field-hint">{t('studio.layeringHint')}</p>}

          {auth.me && auth.me.quota.daily_outfit_limit != null && (
            <p className="field-hint">
              {t('studio.quotaPrefix')}
              {Math.max(0, auth.me.quota.daily_outfit_limit - auth.me.quota.used_today)}
              {t('studio.quotaSuffix')}
            </p>
          )}

          {error && <div className="field-error">{error}</div>}

          <button type="button" className="btn btn-primary btn-block" disabled={generating || !preset || garmentIds.length === 0} onClick={onGenerate}>
            {generating ? <span className="spinner" /> : null}
            {generating ? t('studio.generating') : t('studio.generateButton')}
          </button>
          {garmentIds.length === 0 && <p className="field-hint">{t('studio.needAtLeastOne')}</p>}
        </div>
      </div>
    </div>
  )
}
