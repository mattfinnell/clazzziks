import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addVip,
  listUsers,
  listVips,
  removeVip,
  syncUsers,
  updateVip,
  type User,
  type UserList,
  type Vip,
} from '../api'
import AsciiLogo from '../components/AsciiLogo'
import './Admin.scss'

// Parse a rate-limit input box: blank/"unlimited" -> null (∞), else a number.
function parseLimit(raw: string): number | null {
  const t = raw.trim().toLowerCase()
  if (t === '' || t === 'unlimited' || t === 'inf' || t === '∞') return null
  const n = Number(t)
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : null
}

// Case-insensitive substring match across the given fields; blank query matches all.
function matchesQuery(query: string, ...fields: (string | null | undefined)[]): boolean {
  const t = query.trim().toLowerCase()
  if (!t) return true
  return fields.some((f) => (f ?? '').toLowerCase().includes(t))
}

// Golden-accent row classes: VIPs are highlighted, admins more strongly.
function rowClass(isVip: boolean, isAdmin: boolean): string | undefined {
  const classes = [isVip && 'admin__vip-row', isAdmin && 'admin__admin-row'].filter(Boolean)
  return classes.length ? classes.join(' ') : undefined
}

// Admin-only dashboard: see all users, promote them to VIP, and throttle their
// hourly downloads. Reached via the #/admin hash route; the backend gates the
// API to admins (403 otherwise).
export default function Admin() {
  const qc = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: listUsers })
  const vips = useQuery({ queryKey: ['vips'], queryFn: listVips })

  const [email, setEmail] = useState('')
  const [note, setNote] = useState('')
  const [limit, setLimit] = useState('')
  const [query, setQuery] = useState('')
  const searching = query.trim() !== ''

  // Filtered counts drive the drawer badges so they reflect what's visible.
  const vipMatches = vips.data?.filter((v) => matchesQuery(query, v.email, v.note)).length
  const userMatches = users.data?.users.filter((u) => matchesQuery(query, u.email, u.name)).length

  // Any VIP change can shift both the users table (role/throttle) and the VIP
  // roster, so refresh both after every mutation.
  const refresh = (list?: Vip[]) => {
    if (list) qc.setQueryData(['vips'], list)
    else void qc.invalidateQueries({ queryKey: ['vips'] })
    void qc.invalidateQueries({ queryKey: ['users'] })
  }

  const add = useMutation({
    mutationFn: addVip,
    onSuccess: (list) => {
      refresh(list)
      setEmail('')
      setNote('')
      setLimit('')
    },
  })
  const promote = useMutation({
    mutationFn: (vipEmail: string) => addVip({ email: vipEmail }),
    onSuccess: (list) => refresh(list),
  })
  const remove = useMutation({ mutationFn: removeVip, onSuccess: (list) => refresh(list) })
  const update = useMutation({
    mutationFn: ({ email, rate_limit }: { email: string; rate_limit: number | null }) =>
      updateVip(email, { rate_limit }),
    onSuccess: (list) => refresh(list),
  })
  const sync = useMutation({
    mutationFn: syncUsers,
    onSuccess: (data) => qc.setQueryData(['users'], data),
  })

  const rowBusy = promote.isPending || remove.isPending || update.isPending

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    add.mutate({
      email: email.trim(),
      note: note.trim() || undefined,
      rate_limit: parseLimit(limit),
    })
  }

  return (
    <div className="admin">
      <div className="admin__window">
        <div className="admin__titlebar">
          <span>root@clazzziks: ~/admin</span>
          <a className="admin__back" href="#/">
            ← back
          </a>
        </div>

        <div className="admin__body">
          <AsciiLogo tagline="user & access control" />

          <p className="admin__sub">
            &gt; manual VIP entry — pre-authorize someone before they sign in.
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

            <button type="submit" disabled={add.isPending}>
              {add.isPending ? 'ADDING…' : 'ADD VIP'}
            </button>
          </form>

          {add.isError && (
            <p className="admin__note admin__note--error">
              !! {(add.error as Error)?.message ?? 'failed to add'}
            </p>
          )}

          <div className="admin__search">
            <input
              type="search"
              className="admin__search-input"
              value={query}
              spellCheck={false}
              placeholder="search email or name…"
              aria-label="search users and VIPs"
              onChange={(e) => setQuery(e.target.value)}
            />
            {searching && (
              <button type="button" className="admin__search-clear" onClick={() => setQuery('')}>
                clear
              </button>
            )}
          </div>

          <Collapsible title="VIPs" badge={vipMatches} defaultOpen forceOpen={searching}>
            <Roster
              vips={vips.data}
              status={vips.status}
              error={vips.error}
              query={query}
              onRemove={(e) => remove.mutate(e)}
              onSetLimit={(email, rate_limit) => update.mutate({ email, rate_limit })}
              busy={rowBusy}
            />
          </Collapsible>

          <Collapsible title="ALL USERS" badge={userMatches} forceOpen={searching}>
            <div className="admin__syncrow">
              <button className="admin__sync" disabled={sync.isPending} onClick={() => sync.mutate()}>
                {sync.isPending ? 'SYNCING…' : 'SYNC FROM FIREBASE'}
              </button>
              <span className="admin__synced">
                {users.data?.last_synced_at
                  ? `last synced: ${new Date(users.data.last_synced_at).toLocaleString()}`
                  : 'never synced'}
              </span>
            </div>
            {sync.isError && (
              <p className="admin__note admin__note--error">
                !! {(sync.error as Error)?.message ?? 'sync failed'}
              </p>
            )}
            <Users
              data={users.data}
              status={users.status}
              error={users.error}
              query={query}
              busy={rowBusy}
              onMakeVip={(e) => promote.mutate(e)}
              onRemoveVip={(e) => remove.mutate(e)}
              onSetLimit={(e, rl) => update.mutate({ email: e, rate_limit: rl })}
            />
          </Collapsible>
        </div>
      </div>
    </div>
  )
}

// A collapsible terminal "drawer" used to tuck the VIP and user tables away.
function Collapsible({
  title,
  badge,
  defaultOpen = false,
  forceOpen = false,
  children,
}: {
  title: string
  badge?: number
  defaultOpen?: boolean
  forceOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  // A search keeps the drawer open so matches are visible regardless of state.
  const isOpen = forceOpen || open
  return (
    <div className={`admin__drawer${isOpen ? ' is-open' : ''}`}>
      <button
        type="button"
        className="admin__drawer-toggle"
        aria-expanded={isOpen}
        disabled={forceOpen}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="admin__drawer-caret">{isOpen ? '▾' : '▸'}</span>
        <span className="admin__drawer-title">{title}</span>
        {badge !== undefined && <span className="admin__drawer-badge">{badge}</span>}
      </button>
      {isOpen && <div className="admin__drawer-body">{children}</div>}
    </div>
  )
}

function Users({
  data,
  status,
  error,
  query,
  busy,
  onMakeVip,
  onRemoveVip,
  onSetLimit,
}: {
  data: UserList | undefined
  status: 'pending' | 'error' | 'success'
  error: unknown
  query: string
  busy: boolean
  onMakeVip: (email: string) => void
  onRemoveVip: (email: string) => void
  onSetLimit: (email: string, rate_limit: number | null) => void
}) {
  if (status === 'pending') return <p className="admin__note">&gt; loading users…</p>
  if (status === 'error') {
    return (
      <p className="admin__note admin__note--error">
        !! {(error as Error)?.message ?? 'could not load users'}
      </p>
    )
  }
  if (!data || data.users.length === 0) {
    return (
      <p className="admin__note">
        &gt; no users to show{data && !data.auth_configured ? ' (open mode — Firebase not configured)' : ''}.
      </p>
    )
  }

  const rows = data.users.filter((u) => matchesQuery(query, u.email, u.name))
  if (rows.length === 0) {
    return <p className="admin__note">&gt; no users match “{query.trim()}”.</p>
  }

  return (
    <table className="admin__table">
      <thead>
        <tr>
          <th>email</th>
          <th>name</th>
          <th>✓</th>
          <th>used / hr</th>
          <th>role</th>
          <th>throttle / hr</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((u) => (
          <UserRow
            key={u.email ?? u.name ?? Math.random()}
            user={u}
            busy={busy}
            onMakeVip={onMakeVip}
            onRemoveVip={onRemoveVip}
            onSetLimit={onSetLimit}
          />
        ))}
      </tbody>
    </table>
  )
}

function UserRow({
  user,
  busy,
  onMakeVip,
  onRemoveVip,
  onSetLimit,
}: {
  user: User
  busy: boolean
  onMakeVip: (email: string) => void
  onRemoveVip: (email: string) => void
  onSetLimit: (email: string, rate_limit: number | null) => void
}) {
  const email = user.email
  const role = user.is_admin ? 'admin' : user.is_vip ? 'vip' : 'user'
  const meta = [
    user.provider && `provider: ${user.provider}`,
    user.created_at && `created: ${user.created_at}`,
    user.last_sign_in && `last sign-in: ${user.last_sign_in}`,
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <tr className={rowClass(user.is_vip, user.is_admin)} title={meta || undefined}>
      <td>{email ?? '—'}</td>
      <td>{user.name ?? '—'}</td>
      <td>{user.email_verified ? '✓' : '—'}</td>
      <td>{user.used_this_window}</td>
      <td className="admin__role">{role}</td>
      <td>
        {user.is_vip && email ? (
          <LimitCell value={user.rate_limit} busy={busy} onSave={(rl) => onSetLimit(email, rl)} />
        ) : (
          <span className="admin__muted">default</span>
        )}
      </td>
      <td>
        {!email ? null : user.is_vip ? (
          <button className="admin__remove" disabled={busy} onClick={() => onRemoveVip(email)}>
            remove vip
          </button>
        ) : (
          <button className="admin__makevip" disabled={busy} onClick={() => onMakeVip(email)}>
            make vip
          </button>
        )}
      </td>
    </tr>
  )
}

function Roster({
  vips,
  status,
  error,
  query,
  onRemove,
  onSetLimit,
  busy,
}: {
  vips: Vip[] | undefined
  status: 'pending' | 'error' | 'success'
  error: unknown
  query: string
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

  const rows = vips.filter((v) => matchesQuery(query, v.email, v.note))
  if (rows.length === 0) {
    return <p className="admin__note">&gt; no VIPs match “{query.trim()}”.</p>
  }

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
        {rows.map((v) => (
          <tr key={v.email} className={rowClass(true, v.is_admin)}>
            <td>{v.email}</td>
            <td className="admin__role">{v.is_admin ? 'admin' : 'vip'}</td>
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

// Inline editor for a single rate limit. Blank/"unlimited" -> ∞ (null).
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
