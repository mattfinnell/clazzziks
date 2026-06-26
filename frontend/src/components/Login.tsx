import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import AsciiLogo from './AsciiLogo'
import './Login.scss'

type Mode = 'signin' | 'signup'

// Map the noisy Firebase auth error codes to short, terminal-flavoured messages.
function explain(err: unknown): string {
  const code = (err as { code?: string })?.code ?? ''
  switch (code) {
    case 'auth/invalid-email':
      return 'malformed email address.'
    case 'auth/missing-password':
      return 'password required.'
    case 'auth/weak-password':
      return 'password too weak — min 6 characters.'
    case 'auth/email-already-in-use':
      return 'account already exists — try LOGIN.'
    case 'auth/invalid-credential':
    case 'auth/wrong-password':
    case 'auth/user-not-found':
      return 'invalid credentials.'
    case 'auth/too-many-requests':
      return 'too many attempts — locked out, retry later.'
    default:
      return (err as Error)?.message || 'authentication failed.'
  }
}

export default function Login() {
  const { signInWithGoogle, signInWithEmail, signUpWithEmail } = useAuth()
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(fn: () => Promise<void>) {
    setError(null)
    setBusy(true)
    try {
      await fn()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    void run(() =>
      mode === 'signin'
        ? signInWithEmail(email.trim(), password)
        : signUpWithEmail(email.trim(), password),
    )
  }

  const submitLabel = busy
    ? mode === 'signin'
      ? 'AUTHENTICATING…'
      : 'REGISTERING…'
    : mode === 'signin'
      ? 'LOGIN'
      : 'CREATE ACCOUNT'

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

          <form className="login__form" onSubmit={onSubmit}>
            <label className="login__field">
              <span className="login__label">email</span>
              <input
                type="email"
                className="login__input"
                autoComplete="email"
                spellCheck={false}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={busy}
                required
              />
            </label>
            <label className="login__field">
              <span className="login__label">password</span>
              <input
                type="password"
                className="login__input"
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
                required
              />
            </label>

            <button className="login__btn" type="submit" disabled={busy}>
              {submitLabel}
            </button>
          </form>

          <p className="login__toggle">
            {mode === 'signin' ? '> no account?' : '> already enrolled?'}{' '}
            <button
              type="button"
              className="login__link"
              onClick={() => {
                setMode((m) => (m === 'signin' ? 'signup' : 'signin'))
                setError(null)
              }}
              disabled={busy}
            >
              {mode === 'signin' ? 'CREATE ACCOUNT' : 'LOGIN'}
            </button>
          </p>

          <div className="login__divider">
            <span>or</span>
          </div>

          <button
            className="login__btn login__btn--ghost"
            type="button"
            onClick={() => void run(signInWithGoogle)}
            disabled={busy}
          >
            LOGIN WITH GOOGLE
          </button>

          {error && <p className="login__error">! ERR: {error}</p>}
        </div>
      </div>
    </div>
  )
}
