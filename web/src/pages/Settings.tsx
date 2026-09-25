import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getServerBase, getToken, setServerBase, setToken } from '../api/config'
import { ApiError, getStatus, submitFeedback, type Status } from '../api'
import { useAuth } from '../auth/context'
import { useT } from '../i18n/context'
import { useTheme, type ThemeMode } from '../theme/context'
import './Settings.css'

export default function Settings() {
  const { t, lang, setLang } = useT()
  const { mode, setMode } = useTheme()
  const auth = useAuth()

  const [server, setServer] = useState(getServerBase())
  const [token, setTokenValue] = useState(getToken())
  const [status, setStatus] = useState<Status | null>(null)

  const [feedbackText, setFeedbackText] = useState('')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackError, setFeedbackError] = useState<string | null>(null)
  const [feedbackDone, setFeedbackDone] = useState(false)

  async function onSubmitGeneralFeedback() {
    if (!feedbackText.trim()) return
    setFeedbackSubmitting(true)
    setFeedbackError(null)
    try {
      await submitFeedback({ target_type: 'general', target_id: null, rating: null, text: feedbackText.trim() })
      setFeedbackDone(true)
      setFeedbackText('')
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 令牌/服务器地址存到 localStorage 后（onBlur），立即重新拉取状态和当前用户，
  // 不依赖 React state 变化触发的 effect ——那样会因为 localStorage 还没写入而读到旧值。
  function refetchAfterConfigChange() {
    void getStatus()
      .then(setStatus)
      .catch(() => {
        // 401 等错误已经由统一处理器处理（跳转 /welcome）
      })
    void auth.refresh().catch(() => {
      // 令牌无效时错误已经记录在 auth.error 里，401 的跳转由统一的 401 处理器负责
    })
  }

  return (
    <div className="container settings-page">
      <h1>{t('settings.title')}</h1>

      <div className="card">
        <div className="field">
          <label>{t('settings.language')}</label>
          <select className="input" value={lang} onChange={(e) => setLang(e.target.value as 'zh' | 'en')}>
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>

        <div className="field">
          <label>{t('settings.theme')}</label>
          <select className="input" value={mode} onChange={(e) => setMode(e.target.value as ThemeMode)}>
            <option value="system">{t('settings.themeSystem')}</option>
            <option value="light">{t('settings.themeLight')}</option>
            <option value="dark">{t('settings.themeDark')}</option>
          </select>
        </div>

        <div className="field">
          <label>{t('settings.serverAddress')}</label>
          <input
            className="input"
            value={server}
            placeholder="http://127.0.0.1:8000"
            onChange={(e) => setServer(e.target.value)}
            onBlur={() => {
              setServerBase(server)
              refetchAfterConfigChange()
            }}
          />
          <div className="field-hint">{t('settings.serverAddressHint')}</div>
        </div>

        <div className="field">
          <label>{t('settings.token')}</label>
          <input
            className="input"
            type="password"
            value={token}
            onChange={(e) => setTokenValue(e.target.value)}
            onBlur={() => {
              setToken(token)
              refetchAfterConfigChange()
            }}
          />
          <div className="field-hint">{t('settings.tokenHint')}</div>
        </div>

        {auth.me && auth.me.mode !== 'open' && (
          <div className="field">
            <label>{t('settings.currentUser')}</label>
            <div>{auth.me.name}</div>
            <button type="button" className="btn btn-sm" onClick={auth.logout}>
              {t('settings.logout')}
            </button>
          </div>
        )}
      </div>

      <div className="section-title">
        <h2>{t('feedback.generalTitle')}</h2>
      </div>
      <div className="card feedback-card">
        {feedbackDone ? (
          <p className="field-hint">{t('common.thanks')}</p>
        ) : (
          <>
            <textarea
              className="input"
              rows={3}
              placeholder={t('feedback.generalPlaceholder')}
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
            />
            {feedbackError && <div className="field-error">{feedbackError}</div>}
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={feedbackSubmitting || !feedbackText.trim()}
              onClick={onSubmitGeneralFeedback}
            >
              {feedbackSubmitting ? <span className="spinner" /> : null}
              {feedbackSubmitting ? t('common.submitting') : t('common.submit')}
            </button>
          </>
        )}
      </div>

      <div className="section-title">
        <h2>{t('settings.status')}</h2>
      </div>

      {import.meta.env.VITE_MOCK === '1' && <p className="field-hint">{t('settings.mockWarning')}</p>}

      {status && (
        <div className="card status-card">
          <div className="feature-row">
            <span>{t('settings.featureAnalyzer')}</span>
            <span className={`badge ${status.features.analyzer ? 'badge-ok' : 'badge-bad'}`}>
              {status.features.analyzer ? t('settings.available') : t('settings.unavailable')}
            </span>
          </div>
          <div className="feature-row">
            <span>{t('settings.featureTryon')}</span>
            <span className={`badge ${status.features.tryon ? 'badge-ok' : 'badge-bad'}`}>
              {status.features.tryon ? t('settings.available') : t('settings.unavailable')}
            </span>
          </div>
          <div className="feature-row">
            <span>{t('settings.featureUpscale')}</span>
            <span className={`badge ${status.features.upscale ? 'badge-ok' : 'badge-bad'}`}>
              {status.features.upscale ? t('settings.available') : t('settings.unavailable')}
            </span>
          </div>
          <div className="feature-row">
            <span>{t('settings.featureTurntable')}</span>
            <span className={`badge ${status.features.turntable ? 'badge-ok' : 'badge-bad'}`}>
              {status.features.turntable ? t('settings.available') : t('settings.unavailable')}
            </span>
          </div>

          {Object.keys(status.providers).length > 0 && (
            <table className="provider-table">
              <tbody>
                {Object.entries(status.providers).map(([name, p]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{p.type}</td>
                    <td>
                      <span className={`badge ${p.available ? 'badge-ok' : 'badge-bad'}`}>
                        {p.available ? t('settings.available') : t('settings.unavailable')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {status.warnings.length > 0 && (
            <ul className="warnings">
              {status.warnings.map((w) => (
                <li key={w} className="field-hint">
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="section-title">
        <Link to="/about">{t('settings.aboutLink')}</Link>
      </div>
    </div>
  )
}
