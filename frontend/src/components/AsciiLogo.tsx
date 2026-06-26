import './AsciiLogo.scss'

// figlet "standard" banner for CLAZZZIKS. String.raw keeps the backslashes
// intact so the art isn't mangled by escape sequences.
const BANNER = String.raw`
       ________    ___ _______________   ______ _______
      / ____/ /   /   /__  /__  /__  /  /  _/ //_/ ___/
     / /   / /   / /| | / /  / /  / /   / // ,<  \__ \
    / /___/ /___/ ___ |/ /__/ /__/ /___/ // /| |___/ /
    \____/_____/_/  |_/____/____/____/___/_/ |_/____/
`

export default function AsciiLogo({ tagline }: { tagline?: string }) {
  return (
    <div className="ascii-logo">
      <pre className="ascii-logo__art" role="img" aria-label="CLAZZZIKS">
        {BANNER}
      </pre>
      {tagline && <p className="ascii-logo__tag">{tagline}</p>}
    </div>
  )
}
