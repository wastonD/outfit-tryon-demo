// 多用户鉴权状态：当前用户信息（GET /api/me）、邀请码登录、退出。
// identityVersion 在当前用户真正变化时才 +1，App.tsx 用它作为 <Routes> 的 key，
// 切换/退出账号时强制重新挂载所有页面，清空衣橱、搭配台、历史等页面里缓存的数据，
// 避免残留显示上一个用户的内容。
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError, getMe, type Me } from '../api'
import { clearToken, setToken } from '../api/config'
import { setUnauthorizedHandler } from '../api/authEvents'

const RETURN_TO_KEY = 'outfit.returnTo'

type AuthContextValue = {
  me: Me | null
  loading: boolean
  error: string | null
  identityVersion: number
  login: (token: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<Me>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()

  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [identityVersion, setIdentityVersion] = useState(0)

  const meRef = useRef<Me | null>(null)
  const initializedRef = useRef(false)

  const refresh = useCallback(async (): Promise<Me> => {
    setLoading(true)
    try {
      const result = await getMe()
      if (initializedRef.current && (!meRef.current || meRef.current.user_id !== result.user_id)) {
        setIdentityVersion((v) => v + 1)
      }
      meRef.current = result
      initializedRef.current = true
      setMe(result)
      setError(null)
      return result
    } catch (e) {
      if (initializedRef.current && meRef.current) {
        setIdentityVersion((v) => v + 1)
      }
      meRef.current = null
      initializedRef.current = true
      setMe(null)
      setError(e instanceof ApiError ? e.message : String(e))
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh().catch(() => {
      // 初次加载令牌无效是正常情况（例如多用户模式下还没输入邀请码），
      // 错误已经记录在 error 里，这里不需要额外处理；401 的跳转由 notifyUnauthorized 统一处理。
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      meRef.current = null
      setMe(null)
      if (location.pathname !== '/welcome') {
        try {
          sessionStorage.setItem(RETURN_TO_KEY, location.pathname + location.search)
        } catch {
          // 忽略
        }
      }
      navigate('/welcome')
    })
    return () => setUnauthorizedHandler(null)
  }, [navigate, location])

  const login = useCallback(
    async (token: string) => {
      setToken(token)
      await refresh()
      let returnTo = '/'
      try {
        returnTo = sessionStorage.getItem(RETURN_TO_KEY) ?? '/'
        sessionStorage.removeItem(RETURN_TO_KEY)
      } catch {
        // 忽略
      }
      navigate(returnTo === '/welcome' ? '/' : returnTo)
    },
    [refresh, navigate],
  )

  const logout = useCallback(() => {
    clearToken()
    meRef.current = null
    initializedRef.current = true
    setMe(null)
    setIdentityVersion((v) => v + 1)
    navigate('/welcome')
  }, [navigate])

  const value: AuthContextValue = { me, loading, error, identityVersion, login, logout, refresh }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
