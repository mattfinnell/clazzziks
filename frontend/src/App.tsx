import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Login from './components/Login'
import AuthBar from './components/AuthBar'
import Downloader from './pages/Downloader'
import Admin from './pages/Admin'
import { useAuth } from './auth/AuthContext'
import { fetchMe } from './api'

// Backdrop palm-tree silhouette (see .scene__palm in globals.scss). String.raw
// keeps the backslashes in the frond/trunk art literal.
const PALM = String.raw`
    __ /\ __
  \/  \||/  \/
  /\__\||/__/\
      \||/
       ||
       ||
       ||
      /||\
     /_||_\
`

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
  // Cached by react-query (AuthBar primes the same key); drives the green↔gold
  // console flow. Admins outrank VIPs for the accent tier.
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  const tier = me.data?.is_admin ? 'admin' : me.data?.is_vip ? 'vip' : null

  if (loading) {
    return <div className="app-loading">booting clazzziks</div>
  }

  // Gate the app when Firebase is configured. In open mode (no Firebase env),
  // skip the gate — the backend likewise stays open without credentials.
  if (firebaseEnabled && !user) {
    return <Login />
  }

  return (
    <div className={`crt${tier ? ` crt--${tier}` : ''}`}>
      <div className="scene" aria-hidden="true">
        <div className="scene__sun" />
        <pre className="scene__palm scene__palm--left">{PALM}</pre>
        <pre className="scene__palm scene__palm--right">{PALM}</pre>
      </div>
      <AuthBar />
      {route === '#/admin' ? <Admin /> : <Downloader />}
      <footer className="crt__footer">
        CLAZZZIKS v0.1.0 :: yt-dlp + ffmpeg :: (c) 199x — no rights reserved
      </footer>
    </div>
  )
}
