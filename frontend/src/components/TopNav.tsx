import type { Page } from '../App'
import './TopNav.scss'

interface Props {
  page: Page
  onNav: (p: Page) => void
}

export default function TopNav({ page, onNav }: Props) {
  return (
    <nav className="top-nav">
      <span className="top-nav__brand">CLAZZZIKS</span>
      <div className="top-nav__links">
        <button
          className={`top-nav__link${page === 'Downloader' ? ' top-nav__link--active' : ''}`}
          onClick={() => onNav('Downloader')}
        >
          Downloader
        </button>
      </div>
    </nav>
  )
}
