import './Terms.scss'

// Collapsible Terms of Service. Uses the native <details>/<summary> element so
// it's keyboard-accessible and works without any JS state of its own.
export default function Terms() {
  return (
    <details className="terms">
      <summary className="terms__summary">
        <span className="terms__caret" aria-hidden="true" />
        Terms of Service
      </summary>

      <div className="terms__body">
        <p>
          CLAZZZIKS is provided <strong>as-is</strong>, for personal and educational use only,
          with no warranty of any kind.
        </p>
        <ol className="terms__list">
          <li>
            You are responsible for ensuring you have the right to download and use any audio you
            request. Only download content you own or are permitted to copy.
          </li>
          <li>
            Respect the copyright, terms, and licenses of YouTube, SoundCloud, and the rights
            holders of the source material. CLAZZZIKS does not grant you any rights to that
            content.
          </li>
          <li>
            Do not use this tool to infringe copyright, circumvent DRM, or otherwise break the law
            in your jurisdiction. Some streams are DRM-protected and cannot be downloaded.
          </li>
          <li>
            Downloads are rate-limited and may fail, be incomplete, or be unavailable. Audio quality
            is capped by the source (see the README for details).
          </li>
          <li>
            The operators accept no liability for how the tool is used or for any loss arising from
            its use. Continued use constitutes acceptance of these terms.
          </li>
          <li>
            🖕 If you are being paid to use these audio tracks, you better pay the authors and labels via their offical / licensed channels (Bandcamp, Beatport, Label, ...)
          </li>
        </ol>
      </div>
    </details>
  )
}
