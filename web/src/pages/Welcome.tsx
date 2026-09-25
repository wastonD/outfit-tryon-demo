import { useState } from 'react'
import { ApiError } from '../api'
import { getToken } from '../api/config'
import { useAuth } from '../auth/context'
import { useT } from '../i18n/context'
import './Welcome.css'

export default function Welcome() {
  const { t } = useT()
  const auth = useAuth()
  const [code, setCode] = useState(() => getToken())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!code.trim() || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await auth.login(code.trim())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="container welcome-page">
      <div className="card welcome-card">
        <h1>{t('welcome.title')}</h1>
        <p className="field-hint">{t('welcome.hint')}</p>
        <div className="field">
          <label>{t('welcome.codeLabel')}</label>
          <input
            className="input"
            value={code}
            placeholder={t('welcome.codePlaceholder')}
            disabled={submitting}
            autoFocus
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
        </div>
        {error && <div className="field-error">{error}</div>}
        <button type="button" className="btn btn-primary btn-block" disabled={submitting || !code.trim()} onClick={submit}>
          {submitting ? <span className="spinner" /> : null}
          {t('welcome.submit')}
        </button>
      </div>
    </div>
  )
}
