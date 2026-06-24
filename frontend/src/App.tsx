import Login from './components/Login'
import Downloader from './pages/Downloader'
import { useAuth } from './auth/AuthContext'

export type Page = 'Downloader'

export default function App() {
  const [page, setPage] = useState<Page>('Downloader')
  const { user, loading, firebaseEnabled } = useAuth()

  if (loading) {
    return <div className="app-loading">Loading…</div>
  }

  // Gate the app when Firebase is configured. In open mode (no Firebase env),
  // skip the gate — the backend likewise stays open without credentials.
  if (firebaseEnabled && !user) {
    return <Login />
  }

  return (
    <>
      <TopNav page={page} onNav={setPage} />
      <Downloader />
    </>
  )
}
