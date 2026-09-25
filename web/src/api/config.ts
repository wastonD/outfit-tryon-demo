// 服务器地址和访问令牌，存 localStorage，读写都用 try/catch 包起来。

const SERVER_KEY = 'outfit.server'
const TOKEN_KEY = 'outfit.token'

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 忽略（隐私模式、存储已满等）
  }
}

export function getServerBase(): string {
  return safeGet(SERVER_KEY) ?? ''
}

export function setServerBase(base: string) {
  safeSet(SERVER_KEY, base.trim())
}

export function getToken(): string {
  return safeGet(TOKEN_KEY) ?? ''
}

export function setToken(token: string) {
  safeSet(TOKEN_KEY, token.trim())
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 忽略（隐私模式、存储已满等）
  }
}
