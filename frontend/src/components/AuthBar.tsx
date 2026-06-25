import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { fetchMe } from '../api'
import './AuthBar.scss'

// Minimal signed-in chrome rendered as a terminal status line. Dev's frontend
// update removed the old TopNav (single-page app), so auth UI lives here.
export default function AuthBar() {
  const { user, signOut } = useAuth()
  // Caller status drives the VIP badge + admin link. Cheap, cached by react-query.
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe })

  // Show the bar for a signed-in user, or for an open-mode local admin (no user).
  if (!user && !me.data?.is_admin) return null

  const who = user?.email ?? user?.displayName ?? 'local'
  return (
    <div className="auth-bar">
      <span className="auth-bar__line">
        <span className="auth-bar__prompt">root@clazzziks</span>:~$ session={who}
        {me.data?.is_vip && <span className="auth-bar__badge">VIP</span>}
      </span>
      <span className="auth-bar__nav">
        {me.data?.is_admin && (
          <a className="auth-bar__link" href="#/admin">
            admin
          </a>
        )}
        {user && (
          <button className="auth-bar__signout" onClick={() => void signOut()}>
            logout
          </button>
        )}
      </span>
    </div>
  )
}
