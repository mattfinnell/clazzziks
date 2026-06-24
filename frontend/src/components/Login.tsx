import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import AsciiLogo from './AsciiLogo'
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
      <div className="login__window">
        <div className="login__titlebar">
          <span>guest@clazzziks: ~/login</span>
          <span className="login__btns">[_][ ][x]</span>
        </div>
        <div className="login__body">
          <AsciiLogo tagline="audio extraction terminal // est. 199x" />

          <div className="login__console">
            <p>&gt; AUTHENTICATION REQUIRED.</p>
            <p className="login__dim">&gt; access may require operator approval.</p>
            <p>
              &gt; awaiting credentials<span className="blink">_</span>
            </p>
          </div>

          <button className="login__btn" onClick={onSignIn} disabled={busy}>
            {busy ? 'AUTHENTICATING…' : 'LOGIN WITH GOOGLE'}
          </button>

          {error && <p className="login__error">! ERR: {error}</p>}
        </div>
      </div>
    </div>
  )
}
