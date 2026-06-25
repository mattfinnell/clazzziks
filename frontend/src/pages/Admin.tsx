import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addVip, listVips, removeVip, type Vip } from '../api'
import AsciiLogo from '../components/AsciiLogo'
import './Admin.scss'

// Admin-only dashboard for the VIP group (rate-limit-exempt users). Reached via
// the #/admin hash route; the backend gates the API to admins (403 otherwise).
export default function Admin() {
  const qc = useQueryClient()
  const vips = useQuery({ queryKey: ['vips'], queryFn: listVips })

  const [email, setEmail] = useState('')
  const [note, setNote] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)

  const onListChange = (list: Vip[]) => qc.setQueryData(['vips'], list)

  const add = useMutation({
    mutationFn: addVip,
    onSuccess: (list) => {
      onListChange(list)
      setEmail('')
      setNote('')
      setIsAdmin(false)
    },
  })
  const remove = useMutation({ mutationFn: removeVip, onSuccess: onListChange })

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    add.mutate({ email: email.trim(), note: note.trim() || undefined, is_admin: isAdmin })
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
            removing={remove.isPending}
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
  removing,
}: {
  vips: Vip[] | undefined
  status: 'pending' | 'error' | 'success'
  error: unknown
  onRemove: (email: string) => void
  removing: boolean
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
          <th>note</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {vips.map((v) => (
          <tr key={v.email}>
            <td>{v.email}</td>
            <td>{v.is_admin ? 'admin' : 'vip'}</td>
            <td>{v.note ?? '—'}</td>
            <td>
              <button
                className="admin__remove"
                disabled={removing}
                onClick={() => onRemove(v.email)}
              >
                remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
