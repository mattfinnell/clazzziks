import { useState } from 'react'
import TopNav from './components/TopNav'
import HelloWorld from './pages/HelloWorld'
import Downloader from './pages/Downloader'

export type Page = 'home' | 'download'

export default function App() {
  const [page, setPage] = useState<Page>('home')

  return (
    <>
      <TopNav page={page} onNav={setPage} />
      {page === 'home' ? <HelloWorld /> : <Downloader />}
    </>
  )
}
