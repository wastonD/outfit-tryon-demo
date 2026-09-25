import { Link } from 'react-router-dom'
import { useT } from '../i18n/context'
import './About.css'

export default function About() {
  const { t } = useT()

  return (
    <div className="container about-page">
      <h1>{t('about.title')}</h1>

      <div className="card about-notice">
        <p>{t('about.betaNotice')}</p>
      </div>

      <div className="section-title">
        <h2>{t('about.dataTitle')}</h2>
      </div>
      <p>{t('about.dataBody')}</p>

      <div className="section-title">
        <h2>{t('about.copyrightTitle')}</h2>
      </div>
      <p>{t('about.copyrightBody')}</p>

      <div className="section-title">
        <h2>{t('about.deleteTitle')}</h2>
      </div>
      <p>{t('about.deleteBody')}</p>

      <p className="about-back">
        <Link to="/settings">{t('common.back')}</Link>
      </p>
    </div>
  )
}
