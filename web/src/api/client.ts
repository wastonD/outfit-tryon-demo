import { notifyUnauthorized } from './authEvents'
import { getServerBase, getToken } from './config'
import type {
  Category,
  CreateOutfitRequest,
  FileRef,
  Garment,
  ImportImagesJsonRequest,
  ImportLinkResponse,
  Job,
  Me,
  Outfit,
  Preset,
  ReprocessGarmentRequest,
  Status,
  SubmitFeedbackRequest,
  SubmitFeedbackResponse,
} from './types'

export class ApiError extends Error {
  code: string
  status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

function withToken(url: string): string {
  const token = getToken()
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getServerBase()
  const token = getToken()
  const headers = new Headers(init?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let res: Response
  try {
    res = await fetch(`${base}${path}`, { ...init, headers })
  } catch {
    throw new ApiError('network_error', '无法连接服务器，请检查服务器地址和网络', 0)
  }

  if (res.status === 204) return undefined as T

  const isJson = res.headers.get('content-type')?.includes('application/json')
  const body = isJson ? await res.json().catch(() => null) : null

  if (!res.ok) {
    const err = body?.error
    if (res.status === 401) notifyUnauthorized()
    throw new ApiError(err?.code ?? 'unknown_error', err?.message ?? `请求失败（${res.status}）`, res.status)
  }

  return body as T
}

export function fileUrl(ref: FileRef | null): string {
  if (!ref) return ''
  const base = getServerBase()
  return withToken(`${base}${ref.url}`)
}

export function getStatus(): Promise<Status> {
  return request('/api/status')
}

export function getMe(): Promise<Me> {
  return request('/api/me')
}

export function getPresets(): Promise<{ items: Preset[] }> {
  return request('/api/presets')
}

export function submitFeedback(body: SubmitFeedbackRequest): Promise<SubmitFeedbackResponse> {
  return request('/api/feedback', { method: 'POST', body: JSON.stringify(body) })
}

export function importLink(text: string): Promise<ImportLinkResponse> {
  return request('/api/import/link', { method: 'POST', body: JSON.stringify({ text }) })
}

export function importImagesFiles(
  files: File[],
  meta: { category?: Category; source_url?: string; source_title?: string; source_platform?: string; source_price?: string },
): Promise<{ items: Garment[] }> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  for (const [k, v] of Object.entries(meta)) {
    if (v) form.append(k, v)
  }
  return request('/api/import/images', { method: 'POST', body: form })
}

export function importImagesJson(body: ImportImagesJsonRequest): Promise<{ items: Garment[] }> {
  return request('/api/import/images', { method: 'POST', body: JSON.stringify(body) })
}

export function listGarments(params?: { status?: string; category?: Category }): Promise<{ items: Garment[] }> {
  const q = new URLSearchParams()
  if (params?.status) q.set('status', params.status)
  if (params?.category) q.set('category', params.category)
  const qs = q.toString()
  return request(`/api/garments${qs ? `?${qs}` : ''}`)
}

export function getGarment(id: string): Promise<Garment> {
  return request(`/api/garments/${id}`)
}

export function patchGarment(id: string, category: Category): Promise<Garment> {
  return request(`/api/garments/${id}`, { method: 'PATCH', body: JSON.stringify({ category }) })
}

export function deleteGarment(id: string): Promise<void> {
  return request(`/api/garments/${id}`, { method: 'DELETE' })
}

export function reprocessGarment(id: string, body?: ReprocessGarmentRequest): Promise<Garment> {
  return request(`/api/garments/${id}/reprocess`, { method: 'POST', body: JSON.stringify(body ?? {}) })
}

export function createOutfit(body: CreateOutfitRequest): Promise<Outfit> {
  return request('/api/outfits', { method: 'POST', body: JSON.stringify(body) })
}

export function listOutfits(): Promise<{ items: Outfit[] }> {
  return request('/api/outfits')
}

export function getOutfit(id: string): Promise<Outfit> {
  return request(`/api/outfits/${id}`)
}

export function deleteOutfit(id: string): Promise<void> {
  return request(`/api/outfits/${id}`, { method: 'DELETE' })
}

export function createTurntable(outfitId: string, duration?: number): Promise<Outfit> {
  return request(`/api/outfits/${outfitId}/turntable`, {
    method: 'POST',
    body: JSON.stringify(duration ? { duration } : {}),
  })
}

export function getJob(id: string): Promise<Job> {
  return request(`/api/jobs/${id}`)
}

export function retryJob(id: string): Promise<Job> {
  return request(`/api/jobs/${id}/retry`, { method: 'POST' })
}
