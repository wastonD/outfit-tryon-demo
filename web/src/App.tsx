import { Route, Routes } from 'react-router-dom'
import { Nav } from './components/Nav'
import { useAuth } from './auth/context'
import Wardrobe from './pages/Wardrobe'
import Studio from './pages/Studio'
import LookResult from './pages/LookResult'
import LookHistory from './pages/LookHistory'
import Settings from './pages/Settings'
import Welcome from './pages/Welcome'
import About from './pages/About'

export default function App() {
  const { identityVersion } = useAuth()

  return (
    <>
      <Nav />
      <main className="app-main">
        {/* identityVersion 在当前用户变化（登录/切换令牌/退出）时 +1，
            用它做 key 强制重新挂载所有页面，清空衣橱/搭配台/历史里缓存的数据。 */}
        <Routes key={identityVersion}>
          <Route path="/welcome" element={<Welcome />} />
          <Route path="/" element={<Wardrobe />} />
          <Route path="/studio" element={<Studio />} />
          <Route path="/looks" element={<LookHistory />} />
          <Route path="/looks/:id" element={<LookResult />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/about" element={<About />} />
        </Routes>
      </main>
    </>
  )
}
