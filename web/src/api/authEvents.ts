// 401 统一处理：client.ts（真实接口）和 mock.ts（假接口）在鉴权失败时都调用 notifyUnauthorized()，
// 由 AuthProvider 注册的 handler 负责跳转到 /welcome，这样每个页面不需要各自处理 401。
type Handler = () => void

let handler: Handler | null = null

export function setUnauthorizedHandler(fn: Handler | null) {
  handler = fn
}

export function notifyUnauthorized() {
  handler?.()
}
