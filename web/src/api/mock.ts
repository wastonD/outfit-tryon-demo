// 假接口：VITE_MOCK=1 时启用，数据放在内存里（刷新页面会丢失），用 setTimeout 模拟
// pending → ready 的状态变化和试衣进度。图片全部是 public/mock/ 下自己画的 SVG（和一段本地生成的占位视频）。
import { notifyUnauthorized } from './authEvents'
import { ApiError } from './client'
import { getToken } from './config'
import type {
  Analysis,
  Category,
  CreateOutfitRequest,
  FeedbackTargetType,
  FileRef,
  Garment,
  ImportImagesJsonRequest,
  ImportLinkResponse,
  Job,
  Me,
  Outfit,
  Preset,
  ReprocessGarmentRequest,
  Source,
  Status,
  SubmitFeedbackRequest,
  SubmitFeedbackResponse,
} from './types'

// 多用户假接口：VITE_MOCK_MODE=open|single|multi（默认 open，和之前的行为一致，不鉴权）。
// multi 模式内置两个假令牌，衣橱、任务、搭配数据按 user_id 分开存放，用来验证"切换用户后数据隔离"。
const MOCK_MODE: 'open' | 'single' | 'multi' = (import.meta.env.VITE_MOCK_MODE as 'open' | 'single' | 'multi' | undefined) ?? 'open'
const SINGLE_MODE_TOKEN = 'demo-token'
const MULTI_MODE_USERS: Record<string, { user_id: string; name: string }> = {
  'demo-token-1': { user_id: 'u1', name: '小王' },
  'demo-token-2': { user_id: 'u2', name: '小李' },
}

// 不带 quota 字段的用户身份；quota 只在 getMe() 里组装（否则每个用别处的调用都要造一份假数据）。
type UserIdentity = Omit<Me, 'quota'>

function resolveUser(): UserIdentity | null {
  if (MOCK_MODE === 'open') return { user_id: 'local', name: 'local', mode: 'open' }
  const token = getToken()
  if (MOCK_MODE === 'single') {
    return token === SINGLE_MODE_TOKEN ? { user_id: 'default', name: 'default', mode: 'single' } : null
  }
  const found = MULTI_MODE_USERS[token]
  return found ? { ...found, mode: 'multi' } : null
}

function requireUser(): UserIdentity {
  const user = resolveUser()
  if (!user) {
    notifyUnauthorized()
    throw new ApiError('unauthorized', '令牌无效或已过期，请重新输入邀请码', 401)
  }
  return user
}

// ---- 每日额度（v1.4）：open 模式不限；single/multi 模式给一个较小的演示上限，方便手动触发 429。----
const DEMO_DAILY_LIMIT = 5
type QuotaState = { limit: number | null; usedToday: number; dateKey: string }
const quotaByUser = new Map<string, QuotaState>()

function beijingDateKey(): string {
  const beijing = new Date(Date.now() + 8 * 3600 * 1000)
  return beijing.toISOString().slice(0, 10)
}

function getQuota(user: UserIdentity): QuotaState {
  const dateKey = beijingDateKey()
  const existing = quotaByUser.get(user.user_id)
  if (existing && existing.dateKey === dateKey) return existing
  const fresh: QuotaState = { limit: user.mode === 'open' ? null : DEMO_DAILY_LIMIT, usedToday: 0, dateKey }
  quotaByUser.set(user.user_id, fresh)
  return fresh
}

// GPU 生成类操作（创建搭配、生成 360°、重试试衣/转盘任务）发起前调用，超额直接抛 429。
function consumeQuota(user: UserIdentity) {
  const quota = getQuota(user)
  if (quota.limit != null && quota.usedToday >= quota.limit) {
    throw new ApiError(
      'quota_exceeded',
      `今日生成次数已用完（上限 ${quota.limit} 次），北京时间 0 点重置`,
      429,
    )
  }
  quota.usedToday++
}

function bucket<T>(store: Map<string, Map<string, T>>, userId: string): Map<string, T> {
  let m = store.get(userId)
  if (!m) {
    m = new Map()
    store.set(userId, m)
  }
  return m
}

const TRYON_CATEGORIES: Category[] = ['top', 'outer', 'bottom', 'skirt', 'dress']
const COLORS = ['黑色', '白色', '米白', '藏青', '浅蓝', '酒红', '军绿', '灰色']

// female-medium-regular-light 和 male-medium-regular-light 各放了多个候选形象（id 加 -2/-3 后缀），
// 用来在 mock 下练"换一个形象"功能；排在前面的 id 不带后缀，是推荐（默认）形象。
const PRESETS: Preset[] = [
  {
    id: 'female-medium-regular-light',
    name: { zh: '女款 · 中等身高 · 标准体型 · 浅肤色 · 形象 1', en: 'Female · Medium · Regular · Light · Look 1' },
    body: { gender: 'female', height: 'medium', build: 'regular', skin: 'light' },
    image: { url: '/mock/model-female-medium-regular-light.svg', mime: 'image/svg+xml' },
    internal_only: false,
  },
  {
    id: 'female-medium-regular-light-2',
    name: { zh: '女款 · 中等身高 · 标准体型 · 浅肤色 · 形象 2', en: 'Female · Medium · Regular · Light · Look 2' },
    body: { gender: 'female', height: 'medium', build: 'regular', skin: 'light' },
    image: { url: '/mock/model-female-medium-regular-light-2.svg', mime: 'image/svg+xml' },
    internal_only: false,
  },
  {
    id: 'female-medium-regular-light-3',
    name: { zh: '女款 · 中等身高 · 标准体型 · 浅肤色 · 形象 3', en: 'Female · Medium · Regular · Light · Look 3' },
    body: { gender: 'female', height: 'medium', build: 'regular', skin: 'light' },
    image: { url: '/mock/model-female-medium-regular-light-3.svg', mime: 'image/svg+xml' },
    internal_only: false,
  },
  {
    id: 'male-medium-regular-light',
    name: { zh: '男款 · 中等身高 · 标准体型 · 浅肤色 · 形象 1', en: 'Male · Medium · Regular · Light · Look 1' },
    body: { gender: 'male', height: 'medium', build: 'regular', skin: 'light' },
    image: { url: '/mock/model-male-medium-regular-light.svg', mime: 'image/svg+xml' },
    internal_only: false,
  },
  {
    id: 'male-medium-regular-light-2',
    name: { zh: '男款 · 中等身高 · 标准体型 · 浅肤色 · 形象 2', en: 'Male · Medium · Regular · Light · Look 2' },
    body: { gender: 'male', height: 'medium', build: 'regular', skin: 'light' },
    image: { url: '/mock/model-male-medium-regular-light-2.svg', mime: 'image/svg+xml' },
    internal_only: false,
  },
  {
    id: 'female-tall-slim-medium',
    name: { zh: '女款 · 高挑 · 偏瘦 · 中等肤色', en: 'Female · Tall · Slim · Medium' },
    body: { gender: 'female', height: 'tall', build: 'slim', skin: 'medium' },
    image: { url: '/mock/model-female-tall-slim-medium.svg', mime: 'image/svg+xml' },
    internal_only: false,
  },
  {
    id: 'male-short-plus-dark',
    name: { zh: '男款 · 偏矮 · 偏胖 · 深肤色（测试用）', en: 'Male · Short · Plus · Dark (test)' },
    body: { gender: 'male', height: 'short', build: 'plus', skin: 'dark' },
    image: { url: '/mock/model-male-short-plus-dark.svg', mime: 'image/svg+xml' },
    internal_only: true,
  },
]

const garmentsByUser = new Map<string, Map<string, Garment>>()
const jobsByUser = new Map<string, Map<string, Job>>()
const outfitsByUser = new Map<string, Map<string, Outfit>>()

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function genId(): string {
  const bytes = new Uint8Array(6)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function nowIso(): string {
  return new Date().toISOString().replace(/\.\d+Z$/, 'Z')
}

function pickColor(): string {
  return COLORS[Math.floor(Math.random() * COLORS.length)]
}

let categoryCursor = 0
function nextCategory(): Category {
  const c = TRYON_CATEGORIES[categoryCursor % TRYON_CATEGORIES.length]
  categoryCursor++
  return c
}

function guessCategoryFromUrl(url: string): Category | undefined {
  const m = /garment-(top|outer|bottom|skirt|dress)/.exec(url)
  return m ? (m[1] as Category) : undefined
}

function layerOf(category: Category): Analysis['layer'] {
  if (category === 'outer') return 'outer'
  if (category === 'top' || category === 'dress') return 'inner'
  return 'none'
}

function detectPlatform(text: string): string {
  const t = text.toLowerCase()
  if (t.includes('taobao') || t.includes('tb.cn')) return 'taobao'
  if (t.includes('jd.com') || t.includes('3.cn')) return 'jd'
  if (t.includes('pinduoduo') || t.includes('pdd')) return 'pdd'
  if (t.includes('douyin')) return 'douyin'
  if (t.includes('uniqlo')) return 'uniqlo'
  return 'other'
}

function platformLabel(p: string): string {
  const map: Record<string, string> = { taobao: '淘宝', jd: '京东', pdd: '拼多多', douyin: '抖音', uniqlo: '优衣库', other: '其他平台' }
  return map[p] ?? p
}

function createJob(kind: Job['kind'], targetId: string, userId: string): Job {
  const id = genId()
  const job: Job = {
    id,
    kind,
    target_id: targetId,
    status: 'queued',
    progress: { done: 0, total: kind === 'turntable' ? 3 : 2, note: '等待中' },
    // mock 用一个随机的排队长度模拟"前面还有几个任务"，真实后端按实际队列长度计算。
    queue_position: Math.floor(Math.random() * 3),
    error: null,
    created_at: nowIso(),
    updated_at: nowIso(),
  }
  bucket(jobsByUser, userId).set(id, job)
  return job
}

// 排队阶段：每 500ms 把 queue_position 减 1，减到 0 后把任务标记为 running 并调用 start() 开始真正处理。
function runQueueThenStart(job: Job, start: () => void) {
  const step = () => {
    if ((job.queue_position ?? 0) <= 0) {
      job.queue_position = null
      job.status = 'running'
      job.updated_at = nowIso()
      start()
      return
    }
    setTimeout(() => {
      job.queue_position = (job.queue_position ?? 1) - 1
      job.updated_at = nowIso()
      step()
    }, 500)
  }
  step()
}

// 测试用触发词（写进衣物来源标题/图片地址里即可）：包含 "fail" 模拟"需要手动选类型"，
// 包含 "error" 模拟"处理失败、可重试"。其余情况正常识别成功。
function simulatePrepareGarment(
  g: Garment,
  job: Job,
  opts: { guessedCategory?: Category; forceFail?: 'category_required' | 'prepare_failed' },
) {
  runQueueThenStart(job, () => runPrepareGarment(g, job, opts))
}

function runPrepareGarment(
  g: Garment,
  job: Job,
  opts: { guessedCategory?: Category; forceFail?: 'category_required' | 'prepare_failed' },
) {
  setTimeout(() => {
    job.progress = { done: 1, total: 2, note: '识别中' }
    job.updated_at = nowIso()
  }, 300)
  setTimeout(() => {
    if (opts.forceFail === 'category_required') {
      g.status = 'failed'
      g.error = { code: 'category_required', message: 'AI 无法识别服装类型，请手动选择类型' }
      job.status = 'failed'
      job.error = g.error
    } else if (opts.forceFail === 'prepare_failed') {
      g.status = 'failed'
      g.error = { code: 'prepare_failed', message: '处理失败（模拟数据），可以点重试' }
      job.status = 'failed'
      job.error = g.error
    } else {
      const category = opts.guessedCategory ?? nextCategory()
      const shot: Analysis['shot'] = Math.random() < 0.3 ? 'worn_by_model' : 'flat_lay'
      g.analysis = {
        category,
        layer: layerOf(category),
        shot,
        tryon_ready: TRYON_CATEGORIES.includes(category),
        color: pickColor(),
        note: '模拟识别结果（mock）',
      }
      if (!g.category) {
        g.category = category
        g.category_source = 'ai'
      }
      if (shot === 'worn_by_model') {
        // mock 没有真的抠图算法，直接复用原图代表"已抠图"
        g.cutout = { url: g.image.url, mime: g.image.mime }
      }
      g.status = 'ready'
      job.status = 'succeeded'
    }
    job.progress = { done: 2, total: 2, note: job.status === 'succeeded' ? '完成' : '失败' }
    job.updated_at = nowIso()
  }, 1400)
}

function createGarmentRecord(
  userId: string,
  image: FileRef,
  source: Source,
  userCategory: Category | undefined,
  identifier: string,
): Garment {
  const id = genId()
  const g: Garment = {
    id,
    status: 'pending',
    error: null,
    category: userCategory ?? null,
    category_source: userCategory ? 'user' : null,
    analysis: null,
    image,
    cutout: null,
    source,
    job_id: null,
    created_at: nowIso(),
  }
  bucket(garmentsByUser, userId).set(id, g)
  const job = createJob('prepare_garment', id, userId)
  g.job_id = job.id

  const lower = identifier.toLowerCase()
  if (userCategory) {
    simulatePrepareGarment(g, job, { guessedCategory: userCategory })
  } else if (lower.includes('fail')) {
    simulatePrepareGarment(g, job, { forceFail: 'category_required' })
  } else if (lower.includes('error')) {
    simulatePrepareGarment(g, job, { forceFail: 'prepare_failed' })
  } else {
    simulatePrepareGarment(g, job, { guessedCategory: guessCategoryFromUrl(image.url) ?? nextCategory() })
  }
  return g
}

export async function getMe(): Promise<Me> {
  await sleep(80)
  const user = requireUser()
  const quota = getQuota(user)
  return { ...user, quota: { daily_outfit_limit: quota.limit, used_today: quota.usedToday } }
}

export async function getStatus(): Promise<Status> {
  await sleep(100)
  requireUser()
  const provider = (type: string) => ({
    type,
    capabilities: [type],
    available: true,
    reason: '',
    commercial_ok: true,
    license: 'mock',
    cost_per_call: 0,
  })
  return {
    providers: {
      'mock-analyzer': provider('analyzer'),
      'mock-tryon': provider('tryon'),
      'mock-upscale': provider('upscale'),
      'mock-turntable': provider('turntable'),
    },
    routes: {
      analyzer: ['mock-analyzer'],
      tryon: ['mock-tryon'],
      upscale: ['mock-upscale'],
      turntable: ['mock-turntable'],
    },
    warnings: ['当前使用前端假接口（VITE_MOCK=1），数据不会持久化，刷新页面会重置'],
    features: { analyzer: true, tryon: true, upscale: true, turntable: true },
  }
}

export async function getPresets(): Promise<{ items: Preset[] }> {
  await sleep(100)
  requireUser()
  return { items: PRESETS }
}

export async function importLink(text: string): Promise<ImportLinkResponse> {
  await sleep(500)
  requireUser()
  if (!/https?:\/\//i.test(text)) {
    throw new ApiError('no_url', '文本里没有链接', 400)
  }
  if (/fail|失败/i.test(text)) {
    throw new ApiError('resolve_failed', '解析失败，建议使用浏览器插件或直接拖入图片导入', 422)
  }
  const platform = detectPlatform(text)
  const pool = ['garment-top', 'garment-outer', 'garment-bottom', 'garment-skirt', 'garment-dress']
  const images = [...pool]
    .sort(() => Math.random() - 0.5)
    .slice(0, 2 + Math.floor(Math.random() * 3))
    .map((name) => `/mock/${name}.svg`)
  return {
    product: {
      url: /https?:\/\/\S+/i.exec(text)?.[0] ?? null,
      platform,
      title: `示例商品 · ${platformLabel(platform)}`,
      price: (Math.random() * 300 + 59).toFixed(2),
      images,
    },
  }
}

export async function importImagesFiles(
  files: File[],
  meta: { category?: Category; source_url?: string; source_title?: string; source_platform?: string; source_price?: string },
): Promise<{ items: Garment[] }> {
  await sleep(200)
  const user = requireUser()
  if (files.length === 0) throw new ApiError('no_images', '没有选择图片', 400)
  const source: Source = {
    url: meta.source_url ?? null,
    title: meta.source_title ?? null,
    platform: meta.source_platform ?? null,
    price: meta.source_price ?? null,
    image_url: null,
  }
  const items = files.map((file) =>
    createGarmentRecord(
      user.user_id,
      { url: URL.createObjectURL(file), mime: file.type || null },
      source,
      meta.category,
      file.name,
    ),
  )
  return { items }
}

export async function importImagesJson(body: ImportImagesJsonRequest): Promise<{ items: Garment[] }> {
  await sleep(200)
  const user = requireUser()
  if (!body.images || body.images.length === 0) throw new ApiError('no_images', '没有图片', 400)
  const source: Source = {
    url: body.source?.url ?? null,
    title: body.source?.title ?? null,
    platform: body.source?.platform ?? null,
    price: body.source?.price ?? null,
    image_url: null,
  }
  const items = body.images.map((item) => {
    const url = 'url' in item ? item.url : item.data_uri
    return createGarmentRecord(user.user_id, { url, mime: null }, source, item.category, url)
  })
  return { items }
}

export async function listGarments(params?: { status?: string; category?: Category }): Promise<{ items: Garment[] }> {
  await sleep(80)
  const user = requireUser()
  let items = Array.from(bucket(garmentsByUser, user.user_id).values())
  if (params?.status) items = items.filter((g) => g.status === params.status)
  if (params?.category) items = items.filter((g) => g.category === params.category)
  items.sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  return { items: items.map((g) => ({ ...g })) }
}

export async function getGarment(id: string): Promise<Garment> {
  await sleep(60)
  const user = requireUser()
  const g = bucket(garmentsByUser, user.user_id).get(id)
  if (!g) throw new ApiError('not_found', '找不到该衣物', 404)
  return { ...g }
}

export async function patchGarment(id: string, category: Category): Promise<Garment> {
  await sleep(150)
  const user = requireUser()
  const g = bucket(garmentsByUser, user.user_id).get(id)
  if (!g) throw new ApiError('not_found', '找不到该衣物', 404)
  g.category = category
  g.category_source = 'user'
  if (g.status === 'failed' && g.error?.code === 'category_required') {
    g.status = 'ready'
    g.error = null
    g.analysis = {
      category,
      layer: layerOf(category),
      shot: 'flat_lay',
      tryon_ready: TRYON_CATEGORIES.includes(category),
      color: pickColor(),
      note: '用户手动指定类型',
    }
  }
  return { ...g }
}

export async function deleteGarment(id: string): Promise<void> {
  await sleep(100)
  const user = requireUser()
  bucket(garmentsByUser, user.user_id).delete(id)
}

export async function reprocessGarment(id: string, opts?: ReprocessGarmentRequest): Promise<Garment> {
  await sleep(100)
  const user = requireUser()
  const g = bucket(garmentsByUser, user.user_id).get(id)
  if (!g) throw new ApiError('not_found', '找不到该衣物', 404)
  if (g.status === 'pending' || g.status === 'processing') {
    throw new ApiError('garment_busy', '该衣物正在处理中，请稍后再试', 409)
  }
  g.status = 'pending'
  g.error = null
  const job = createJob('prepare_garment', id, user.user_id)
  g.job_id = job.id
  simulateReprocess(g, job, opts?.force_segment ?? false)
  return { ...g }
}

function simulateReprocess(g: Garment, job: Job, forceSegment: boolean) {
  runQueueThenStart(job, () => runReprocess(g, job, forceSegment))
}

function runReprocess(g: Garment, job: Job, forceSegment: boolean) {
  setTimeout(() => {
    job.progress = { done: 1, total: 2, note: forceSegment ? '重新抠图中' : '重新识别中' }
    job.updated_at = nowIso()
  }, 300)
  setTimeout(() => {
    const category = g.category ?? nextCategory()
    const shot: Analysis['shot'] = forceSegment ? 'worn_by_model' : Math.random() < 0.3 ? 'worn_by_model' : 'flat_lay'
    g.analysis = {
      category,
      layer: layerOf(category),
      shot,
      tryon_ready: TRYON_CATEGORIES.includes(category),
      color: pickColor(),
      note: forceSegment ? '按当前类型强制重新抠图（mock）' : '重新识别结果（mock）',
    }
    if (!g.category) {
      g.category = category
      g.category_source = 'ai'
    }
    g.cutout = forceSegment || shot === 'worn_by_model' ? { url: g.image.url, mime: g.image.mime } : null
    g.status = 'ready'
    job.status = 'succeeded'
    job.progress = { done: 2, total: 2, note: '完成' }
    job.updated_at = nowIso()
  }, 1200)
}

export async function createOutfit(body: CreateOutfitRequest): Promise<Outfit> {
  await sleep(200)
  const user = requireUser()
  const preset = PRESETS.find((p) => p.id === body.preset_id)
  if (!preset) throw new ApiError('preset_not_found', '找不到该模特', 404)
  if (body.garment_ids.length === 0) throw new ApiError('nothing_to_try_on', '没有选择衣物', 422)
  const userGarments = bucket(garmentsByUser, user.user_id)
  const gs = body.garment_ids.map((id) => userGarments.get(id))
  if (gs.some((g) => !g)) throw new ApiError('garment_not_found', '找不到该衣物', 404)
  const ready = gs as Garment[]
  if (ready.some((g) => g.status !== 'ready')) throw new ApiError('garment_not_ready', '有衣物还没准备好', 422)
  const tryable = ready.filter((g) => g.category && TRYON_CATEGORIES.includes(g.category))
  if (tryable.length === 0) throw new ApiError('nothing_to_try_on', '没有可以试穿的服装类型', 422)
  const skipped = ready.filter((g) => !tryable.includes(g)).map((g) => g.id)

  consumeQuota(user)

  const id = genId()
  const job = createJob('tryon', id, user.user_id)
  const outfit: Outfit = {
    id,
    preset_id: body.preset_id,
    garment_ids: body.garment_ids,
    options: { tuck: body.options?.tuck ?? 'auto', upscale: body.options?.upscale ?? false },
    status: 'queued',
    error: null,
    job_id: job.id,
    result: null,
    turntable: { status: 'none', job_id: null, video: null, provider: null, error: null },
    created_at: nowIso(),
  }
  bucket(outfitsByUser, user.user_id).set(id, outfit)
  simulateTryon(outfit, job, tryable.map((g) => g.id), skipped)
  return outfit
}

function simulateTryon(outfit: Outfit, job: Job, tryableIds: string[], skipped: string[]) {
  runQueueThenStart(job, () => runTryon(outfit, job, tryableIds, skipped))
}

function runTryon(outfit: Outfit, job: Job, tryableIds: string[], skipped: string[]) {
  outfit.status = 'running'
  const stepDelay = 900
  const total = tryableIds.length + (outfit.options.upscale ? 1 : 0)
  const steps: NonNullable<Outfit['result']>['steps'] = []
  const resultImage: FileRef = { url: '/mock/result-composite.svg', mime: 'image/svg+xml' }

  const runStep = (i: number) => {
    if (i >= total) {
      outfit.result = {
        image: resultImage,
        provider: 'mock-tryon',
        total_seconds: +((total * stepDelay) / 1000).toFixed(1),
        total_cost: null,
        skipped_garment_ids: skipped,
        cached: false,
        steps,
      }
      outfit.status = 'ready'
      job.status = 'succeeded'
      job.progress = { done: total, total, note: '完成' }
      job.updated_at = nowIso()
      return
    }
    setTimeout(() => {
      const isUpscaleStep = i >= tryableIds.length
      steps.push({
        garment_ids: isUpscaleStep ? [] : [tryableIds[i]],
        image: resultImage,
        seconds: stepDelay / 1000,
      })
      job.progress = { done: i + 1, total, note: isUpscaleStep ? '高清放大中' : `第 ${i + 1} 步：试穿中` }
      job.updated_at = nowIso()
      runStep(i + 1)
    }, stepDelay)
  }
  runStep(0)
}

export async function listOutfits(): Promise<{ items: Outfit[] }> {
  await sleep(80)
  const user = requireUser()
  const items = Array.from(bucket(outfitsByUser, user.user_id).values()).sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  return { items: items.map((o) => ({ ...o })) }
}

export async function getOutfit(id: string): Promise<Outfit> {
  await sleep(60)
  const user = requireUser()
  const o = bucket(outfitsByUser, user.user_id).get(id)
  if (!o) throw new ApiError('not_found', '找不到该搭配', 404)
  return { ...o }
}

export async function deleteOutfit(id: string): Promise<void> {
  await sleep(100)
  const user = requireUser()
  bucket(outfitsByUser, user.user_id).delete(id)
}

export async function createTurntable(outfitId: string, _duration?: number): Promise<Outfit> {
  await sleep(150)
  const user = requireUser()
  const outfit = bucket(outfitsByUser, user.user_id).get(outfitId)
  if (!outfit) throw new ApiError('not_found', '找不到该搭配', 404)
  if (outfit.status !== 'ready') throw new ApiError('outfit_not_ready', '搭配还没准备好', 409)
  consumeQuota(user)
  const job = createJob('turntable', outfitId, user.user_id)
  outfit.turntable = { status: 'queued', job_id: job.id, video: null, provider: null, error: null }
  simulateTurntable(outfit, job)
  return outfit
}

function simulateTurntable(outfit: Outfit, job: Job) {
  runQueueThenStart(job, () => runTurntable(outfit, job))
}

function runTurntable(outfit: Outfit, job: Job) {
  outfit.turntable.status = 'running'
  const total = 3
  const step = (done: number) => {
    if (done >= total) {
      outfit.turntable = {
        status: 'ready',
        job_id: job.id,
        video: { url: '/mock/turntable.mp4', mime: 'video/mp4' },
        provider: 'mock-turntable',
        error: null,
      }
      job.status = 'succeeded'
      job.progress = { done: total, total, note: '完成' }
      job.updated_at = nowIso()
      return
    }
    setTimeout(() => {
      job.progress = { done: done + 1, total, note: `渲染第 ${done + 1} 段` }
      job.updated_at = nowIso()
      step(done + 1)
    }, 900)
  }
  step(0)
}

export async function getJob(id: string): Promise<Job> {
  await sleep(50)
  const user = requireUser()
  const job = bucket(jobsByUser, user.user_id).get(id)
  if (!job) throw new ApiError('not_found', '找不到任务', 404)
  return { ...job }
}

export async function retryJob(id: string): Promise<Job> {
  await sleep(100)
  const user = requireUser()
  const job = bucket(jobsByUser, user.user_id).get(id)
  if (!job) throw new ApiError('not_found', '找不到任务', 404)
  if (job.status !== 'failed') throw new ApiError('job_not_failed', '只有失败的任务可以重试', 409)
  // 契约（v1.4 额度）：只有重试 tryon 和 turntable 任务时才计入每日额度，重试识别/抠图不计入。
  if (job.kind === 'tryon' || job.kind === 'turntable') consumeQuota(user)
  job.status = 'queued'
  job.error = null
  job.queue_position = Math.floor(Math.random() * 3)
  job.updated_at = nowIso()
  if (job.kind === 'prepare_garment') {
    const g = bucket(garmentsByUser, user.user_id).get(job.target_id)
    if (g) {
      g.status = 'pending'
      g.error = null
      simulatePrepareGarment(g, job, { guessedCategory: g.category ?? nextCategory() })
    }
  }
  return { ...job }
}

export async function submitFeedback(body: SubmitFeedbackRequest): Promise<SubmitFeedbackResponse> {
  await sleep(150)
  const user = requireUser()
  const hasRating = body.rating != null
  const hasText = body.text != null && body.text.trim().length > 0
  if (!hasRating && !hasText) throw new ApiError('bad_request', 'rating 和 text 至少需要提供一个', 400)
  if (body.text && body.text.length > 1000) throw new ApiError('bad_request', '文字反馈最多 1000 个字符', 400)
  const target_type: FeedbackTargetType = body.target_type
  if (target_type !== 'general') {
    if (!body.target_id) throw new ApiError('bad_request', '缺少 target_id', 400)
    const found =
      target_type === 'outfit'
        ? bucket(outfitsByUser, user.user_id).get(body.target_id)
        : bucket(garmentsByUser, user.user_id).get(body.target_id)
    if (!found) throw new ApiError('not_found', '找不到该资源', 404)
  }
  return { id: genId() }
}
