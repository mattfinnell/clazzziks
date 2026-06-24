import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import './Login.scss'

export default function Login() {
  const { signInWithGoogle } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSignIn() {
    setError(null)
    setBusy(true)
    try {
      await signInWithGoogle()
    } catch (err) {
      setError((err as Error).message || 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <div className="login__card">
        <h1 className="login__brand">CLAZZZIKS</h1>
        <p className="login__sub">Sign in to download audio.</p>
        <button className="login__btn" onClick={onSignIn} disabled={busy}>
          {busy ? 'Signing in…' : 'Continue with Google'}
        </button>
        <p className="login__note">
          Access may require owner approval before downloading.
        </p>
        {error && <p className="login__error">{error}</p>}
      </div>
    </div>
  )
}
