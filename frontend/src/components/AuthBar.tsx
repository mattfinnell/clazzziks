import { useAuth } from '../auth/AuthContext'
import './AuthBar.scss'

// Minimal signed-in chrome rendered as a terminal status line. Dev's frontend
// update removed the old TopNav (single-page app), so auth UI lives here.
export default function AuthBar() {
  const { user, signOut } = useAuth()
  if (!user) return null
  const who = user.email ?? user.displayName ?? 'unknown'
  return (
    <div className="auth-bar">
      <span className="auth-bar__line">
        <span className="auth-bar__prompt">root@clazzziks</span>:~$ session={who}
      </span>
      <button className="auth-bar__signout" onClick={() => void signOut()}>
        logout
      </button>
    </div>
  )
}
