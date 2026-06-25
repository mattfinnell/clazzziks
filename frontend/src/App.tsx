import { useEffect, useState } from 'react'
import Login from './components/Login'
import AuthBar from './components/AuthBar'
import Downloader from './pages/Downloader'
import Admin from './pages/Admin'
import { useAuth } from './auth/AuthContext'

// Tiny hash router — avoids pulling in react-router for a single extra page and
// works under static hosting (S3/CloudFront) without server rewrite rules.
function useHashRoute(): string {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

export default function App() {
  const { user, loading, firebaseEnabled } = useAuth()
  const route = useHashRoute()

  if (loading) {
    return <div className="app-loading">booting clazzziks</div>
  }

  // Gate the app when Firebase is configured. In open mode (no Firebase env),
  // skip the gate — the backend likewise stays open without credentials.
  if (firebaseEnabled && !user) {
    return <Login />
  }

  return (
    <div className="crt">
      <AuthBar />
      {route === '#/admin' ? <Admin /> : <Downloader />}
      <footer className="crt__footer">
        CLAZZZIKS v0.1.0 :: yt-dlp + ffmpeg :: (c) 199x — no rights reserved
      </footer>
    </div>
  )
}
