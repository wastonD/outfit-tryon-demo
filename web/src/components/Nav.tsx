import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { useT } from '../i18n/context'

export function Nav() {
  const { t } = useT()
  const { me } = useAuth()
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : undefined)

  return (
    <nav className="app-nav">
      <div className="container">
        <span className="brand">{t('common.appName')}</span>
        <div className="links">
          <NavLink to="/" end className={cls}>
            {t('nav.wardrobe')}
          </NavLink>
          <NavLink to="/studio" className={cls}>
            {t('nav.studio')}
          </NavLink>
          <NavLink to="/looks" className={cls}>
            {t('nav.looks')}
          </NavLink>
          <NavLink to="/settings" className={cls}>
            {t('nav.settings')}
          </NavLink>
        </div>
        {me && me.mode !== 'open' && <span className="user-name">{me.name}</span>}
      </div>
    </nav>
  )
}
