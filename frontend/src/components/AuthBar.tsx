import { useAuth } from '../auth/AuthContext'
import './AuthBar.scss'

// Minimal signed-in chrome: who you are + a way out. Dev's frontend update
// removed the old TopNav (the app is a single page), so auth UI lives here
// rather than in a navigation bar.
export default function AuthBar() {
  const { user, signOut } = useAuth()
  if (!user) return null
  return (
    <div className="auth-bar">
      <span className="auth-bar__email" title={user.email ?? undefined}>
        {user.email ?? user.displayName ?? 'Signed in'}
      </span>
      <button className="auth-bar__signout" onClick={() => void signOut()}>
        Sign out
      </button>
    </div>
  )
}
