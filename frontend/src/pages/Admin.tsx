import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addVip, listVips, removeVip, updateVip, type Vip } from '../api'
import AsciiLogo from '../components/AsciiLogo'
import './Admin.scss'

// Parse a rate-limit input box: blank/"unlimited" -> null (∞), else a number.
function parseLimit(raw: string): number | null {
  const t = raw.trim().toLowerCase()
  if (t === '' || t === 'unlimited' || t === 'inf' || t === '∞') return null
  const n = Number(t)
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : null
}

// Admin-only dashboard for the VIP group (rate-limit-exempt users). Reached via
// the #/admin hash route; the backend gates the API to admins (403 otherwise).
export default function Admin() {
  const qc = useQueryClient()
  const vips = useQuery({ queryKey: ['vips'], queryFn: listVips })

  const [email, setEmail] = useState('')
  const [note, setNote] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  const [limit, setLimit] = useState('')

  const onListChange = (list: Vip[]) => qc.setQueryData(['vips'], list)

  const add = useMutation({
    mutationFn: addVip,
    onSuccess: (list) => {
      onListChange(list)
      setEmail('')
      setNote('')
      setIsAdmin(false)
      setLimit('')
    },
  })
  const remove = useMutation({ mutationFn: removeVip, onSuccess: onListChange })
  const update = useMutation({
    mutationFn: ({ email, rate_limit }: { email: string; rate_limit: number | null }) =>
      updateVip(email, { rate_limit }),
    onSuccess: onListChange,
  })

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    add.mutate({
      email: email.trim(),
      note: note.trim() || undefined,
      is_admin: isAdmin,
      rate_limit: parseLimit(limit),
    })
  }

  return (
    <div className="admin">
      <div className="admin__window">
        <div className="admin__titlebar">
          <span>root@clazzziks: ~/admin/vip</span>
          <a className="admin__back" href="#/">
            ← back
          </a>
        </div>

        <div className="admin__body">
          <AsciiLogo tagline="vip access control" />
          <p className="admin__sub">
            &gt; VIPs may use the tool without rate-limiting. Admins can manage this list.
          </p>

          <form className="admin__form" onSubmit={onSubmit}>
            <div className="admin__row">
              <div className="admin__grow">
                <label htmlFor="vip-email">email</label>
                <input
                  id="vip-email"
                  type="email"
                  value={email}
                  spellCheck={false}
                  placeholder="friend@example.com"
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="admin__grow">
                <label htmlFor="vip-note">note (optional)</label>
                <input
                  id="vip-note"
                  value={note}
                  spellCheck={false}
                  placeholder="how you know them"
                  onChange={(e) => setNote(e.target.value)}
                />
              </div>
              <div className="admin__limit-field">
                <label htmlFor="vip-limit">rate limit / hr</label>
                <input
                  id="vip-limit"
                  value={limit}
                  spellCheck={false}
                  placeholder="∞"
                  onChange={(e) => setLimit(e.target.value)}
                />
              </div>
            </div>

            <label className="admin__check">
              <input
                type="checkbox"
                checked={isAdmin}
                onChange={(e) => setIsAdmin(e.target.checked)}
              />
              grant admin rights
            </label>

            <button type="submit" disabled={add.isPending}>
              {add.isPending ? 'ADDING…' : 'ADD VIP'}
            </button>
          </form>

          {add.isError && (
            <p className="admin__note admin__note--error">
              !! {(add.error as Error)?.message ?? 'failed to add'}
            </p>
          )}

          <Roster
            vips={vips.data}
            status={vips.status}
            error={vips.error}
            onRemove={(e) => remove.mutate(e)}
            onSetLimit={(email, rate_limit) => update.mutate({ email, rate_limit })}
            busy={remove.isPending || update.isPending}
          />
        </div>
      </div>
    </div>
  )
}

function Roster({
  vips,
  status,
  error,
  onRemove,
  onSetLimit,
  busy,
}: {
  vips: Vip[] | undefined
  status: 'pending' | 'error' | 'success'
  error: unknown
  onRemove: (email: string) => void
  onSetLimit: (email: string, rate_limit: number | null) => void
  busy: boolean
}) {
  if (status === 'pending') return <p className="admin__note">&gt; loading roster…</p>
  if (status === 'error') {
    return (
      <p className="admin__note admin__note--error">
        !! {(error as Error)?.message ?? 'could not load VIPs'}
      </p>
    )
  }
  if (!vips || vips.length === 0) return <p className="admin__note">&gt; no VIPs yet.</p>

  return (
    <table className="admin__table">
      <thead>
        <tr>
          <th>email</th>
          <th>role</th>
          <th>rate limit / hr</th>
          <th>note</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {vips.map((v) => (
          <tr key={v.email}>
            <td>{v.email}</td>
            <td>{v.is_admin ? 'admin' : 'vip'}</td>
            <td>
              <LimitCell
                value={v.rate_limit}
                busy={busy}
                onSave={(rate_limit) => onSetLimit(v.email, rate_limit)}
              />
            </td>
            <td>{v.note ?? '—'}</td>
            <td>
              <button className="admin__remove" disabled={busy} onClick={() => onRemove(v.email)}>
                remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Inline editor for a single VIP's rate limit. Blank/"unlimited" -> ∞ (null).
function LimitCell({
  value,
  busy,
  onSave,
}: {
  value: number | null
  busy: boolean
  onSave: (rate_limit: number | null) => void
}) {
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  const dirty = (parseLimit(draft) ?? null) !== value

  return (
    <span className="admin__limit">
      <input
        className="admin__limit-input"
        value={draft}
        spellCheck={false}
        placeholder="∞"
        onChange={(e) => setDraft(e.target.value)}
      />
      {dirty && (
        <button
          className="admin__limit-save"
          disabled={busy}
          onClick={() => onSave(parseLimit(draft))}
        >
          save
        </button>
      )}
    </span>
  )
}
