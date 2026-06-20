import { useState } from 'react'
import TopNav from './components/TopNav'
import Downloader from './pages/Downloader'

export type Page = 'Downloader' 

export default function App() {
  const [page, setPage] = useState<Page>('Downloader')

  return (
    <>
      <TopNav page={page} onNav={setPage} />
      {<Downloader />}
    </>
  )
}
