// 与后端 server/api/schemas.py 保持一致，字段名不要改。

export type Category = 'top' | 'outer' | 'bottom' | 'skirt' | 'dress' | 'shoes' | 'bag' | 'other'
// 第一版可以试穿的类型：top outer bottom skirt dress（shoes/bag/other 可以导入，但试衣时会被跳过）

export type FileRef = { url: string; mime: string | null } // url 形如 "/files/<sha256>"，前端自己拼服务器地址

export type Source = {
  url: string | null // 商品页地址
  title: string | null
  platform: string | null // taobao | jd | pdd | douyin | uniqlo | other | unknown ...
  price: string | null
  image_url: string | null // 原始图片地址
}

export type Analysis = {
  category: Category
  layer: 'inner' | 'outer' | 'none'
  shot: 'flat_lay' | 'worn_by_model' | 'mannequin' | 'detail' | 'poster' | 'other'
  tryon_ready: boolean
  color: string | null
  note: string | null // 一句话款式描述
}

export type Garment = {
  id: string
  status: 'pending' | 'processing' | 'ready' | 'failed'
  error: { code: string; message: string } | null
  category: Category | null // 识别完成或用户指定前可能为 null
  category_source: 'user' | 'ai' | null
  analysis: Analysis | null
  image: FileRef // 原图
  cutout: FileRef | null // 抠图结果（模特上身图才会有）
  source: Source
  job_id: string | null // 最近一次处理任务
  created_at: string
}

export type Preset = {
  id: string // 例如 "female-medium-regular-light"
  name: { zh: string; en: string }
  body: {
    gender: 'female' | 'male'
    height: 'short' | 'medium' | 'tall'
    build: 'slim' | 'regular' | 'plus'
    skin: 'light' | 'medium' | 'dark'
  }
  image: FileRef
  internal_only: boolean // true = 仅供内部测试的占位图
}
// v1.4：同一个 body 组合可以有多个 Preset（同一体型的不同形象），id 各不相同；
// /api/presets 返回的顺序就是推荐顺序，同一体型里排在前面的是默认形象。

export type Job = {
  id: string
  kind: 'prepare_garment' | 'tryon' | 'turntable'
  target_id: string // garment id 或 outfit id
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  progress: { done: number; total: number; note: string }
  queue_position: number | null // v1.4：status 为 queued 时，同一队列里排在它前面的任务数（0 表示下一个执行）；其他状态为 null
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
}

export type OutfitOptions = { tuck: 'auto' | 'in' | 'out'; upscale: boolean }

export type Outfit = {
  id: string
  preset_id: string
  garment_ids: string[]
  options: OutfitOptions
  status: 'queued' | 'running' | 'ready' | 'failed'
  error: { code: string; message: string } | null
  job_id: string
  result: null | {
    image: FileRef
    provider: string
    total_seconds: number
    total_cost: number | null // 元；null 表示未知
    skipped_garment_ids: string[] // 引擎不支持而跳过的衣物
    cached: boolean
    steps: { garment_ids: string[]; image: FileRef; seconds: number }[]
  }
  turntable: {
    status: 'none' | 'queued' | 'running' | 'ready' | 'failed'
    job_id: string | null
    video: FileRef | null
    provider: string | null
    error: { code: string; message: string } | null
  }
  created_at: string
}

export type Me = {
  user_id: string
  name: string
  mode: 'multi' | 'single' | 'open'
  quota: { daily_outfit_limit: number | null; used_today: number } // v1.4；daily_outfit_limit 为 null 表示不限
}

export type Status = {
  providers: Record<
    string,
    {
      type: string
      capabilities: string[]
      available: boolean
      reason: string
      commercial_ok: boolean
      license: string | null
      cost_per_call: number | null
    }
  >
  routes: Record<string, string[]>
  warnings: string[]
  features: { analyzer: boolean; tryon: boolean; upscale: boolean; turntable: boolean }
  // feature = 对应路由里至少有一个当前可用的实现
}

// ---- 请求体类型（契约里以内联 JSON 描述，这里补上对应的 TS 类型） ----

export type ImportLinkRequest = { text: string }
export type ImportLinkResponse = {
  product: {
    url: string | null
    platform: string | null
    title: string | null
    price: string | null
    images: string[]
  }
}

export type ImportImageItem = { url: string; category?: Category } | { data_uri: string; category?: Category }
export type ImportImagesJsonRequest = {
  images: ImportImageItem[]
  source?: { url?: string; title?: string; platform?: string; price?: string }
}

export type CreateOutfitRequest = {
  preset_id: string
  garment_ids: string[]
  options?: Partial<OutfitOptions>
}

export type ReprocessGarmentRequest = { force_segment?: boolean }

export type FeedbackTargetType = 'outfit' | 'garment' | 'general'
export type SubmitFeedbackRequest = {
  target_type: FeedbackTargetType
  target_id: string | null
  rating: number | null // 1-5
  text: string | null // 最多 1000 字符
}
export type SubmitFeedbackResponse = { id: string }

export type ApiErrorBody = { error: { code: string; message: string } }
