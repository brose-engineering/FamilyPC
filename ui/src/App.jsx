import React, { useCallback, useEffect, useState } from 'react'

const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)familypc_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  if (opts.method && opts.method !== 'GET') headers['X-CSRF-Token'] = csrfToken()
  return fetch(path, { ...opts, headers })
}

function fmtMin(sec) {
  if (sec === null || sec === undefined) return 'unbegrenzt'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m} min ${s > 0 ? `${s} s` : ''}`.trim() : `${s} s`
}

function parseWindows(textByDay) {
  const windows = {}
  for (const [day, text] of Object.entries(textByDay)) {
    const entries = (text || '').split(',').map((s) => s.trim()).filter(Boolean)
    const list = []
    for (const e of entries) {
      const m = e.match(/^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$/)
      if (!m) throw new Error(`Ungueltiges Fenster "${e}" (Format HH:MM-HH:MM)`)
      list.push({ start: m[1].padStart(5, '0'), end: m[2].padStart(5, '0') })
    }
    if (list.length) windows[Number(day)] = list
  }
  return windows
}

function windowsToText(windows) {
  const out = {}
  for (let d = 0; d < 7; d++) {
    const list = (windows && windows[String(d)]) || []
    out[d] = list.map((w) => `${w.start}-${w.end}`).join(', ')
  }
  return out
}

function emptyForm() {
  return { daily_budget_minutes: '', internet_enabled: true, internet_daily_budget_minutes: '', windowsText: windowsToText({}) }
}

function formFromAccount(a) {
  return {
    daily_budget_minutes: a.daily_budget_minutes ?? '',
    internet_enabled: a.internet_enabled ?? true,
    internet_daily_budget_minutes: a.internet_daily_budget_minutes ?? '',
    windowsText: windowsToText(a.windows),
  }
}

function Login({ onLogin, err }) {
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="wrap login">
      <h1 className="brand">FamilyPC</h1>
      <p className="meta">Anmeldung mit Panel-Account (Eltern)</p>
      {err && <p className="err">{err}</p>}
      <label>Benutzer<br /><input value={user} onChange={(e) => setUser(e.target.value)} autoFocus /></label>
      <label>Passwort<br /><input type="password" value={pw} onChange={(e) => setPw(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && !busy && onLogin(user, pw, setBusy, setPw)} /></label>
      <button disabled={busy || !user || !pw} onClick={() => onLogin(user, pw, setBusy, setPw)}>Anmelden</button>
    </div>
  )
}

export default function App() {
  const [auth, setAuth] = useState(undefined) // undefined = pruefen, null = Login noetig
  const [loginErr, setLoginErr] = useState(null)
  const [status, setStatus] = useState(null)
  const [config, setConfig] = useState(null)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [editUser, setEditUser] = useState(null)
  const [form, setForm] = useState(emptyForm())
  const [newUser, setNewUser] = useState('')
  const [users, setUsers] = useState([])

  async function handleLogin(user, pw, setBusy) {
    setBusy(true)
    setLoginErr(null)
    try {
      const r = await api('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: user, password: pw }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setLoginErr(d.detail || `HTTP ${r.status}`)
        return
      }
      setAuth(user)
    } finally {
      setBusy(false)
    }
  }

  async function handleLogout() {
    await api('/api/logout', { method: 'POST' })
    setAuth(null)
    setStatus(null)
    setConfig(null)
  }

  const load = useCallback(async () => {
    try {
      const who = await api('/api/whoami')
      if (who.status === 401) {
        setAuth(null)
        return
      }
      setAuth((await who.json()).user)
      const [c, u] = await Promise.all([api('/api/config'), api('/api/users')])
      setConfig(await c.json())
      setUsers((await u.json()).users || [])
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // FAM-14: Live-Restzeiten per Server-Sent-Events (Fallback: Poll alle 5 s)
  useEffect(() => {
    if (!auth) return
    let es = null
    let poll = null
    const startPoll = () => {
      if (poll) return
      poll = setInterval(async () => {
        const r = await api('/api/status')
        if (r.status === 200) setStatus(await r.json())
      }, 5000)
    }
    try {
      es = new EventSource('/api/events')
      es.onmessage = (e) => setStatus(JSON.parse(e.data))
      es.onerror = () => { es && es.close(); es = null; startPoll() }
    } catch {
      startPoll()
    }
    return () => { if (es) es.close(); if (poll) clearInterval(poll) }
  }, [auth])

  async function extend(user, minutes) {
    const r = await api(`/api/accounts/${encodeURIComponent(user)}/extend`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ minutes }),
    })
    if (r.ok) {
      setMsg(`${user}: +${minutes} min (neues Tagesbudget siehe Liste).`)
      setConfig(await (await api('/api/config')).json())
    } else setMsg(`Fehler: HTTP ${r.status}`)
  }

  async function terminateSession(user) {
    if (!confirm(`Session von ${user} jetzt beenden?`)) return
    const r = await api(`/api/accounts/${encodeURIComponent(user)}/terminate`, { method: 'POST' })
    setMsg(r.ok ? `Session von ${user} beendet.` : `Fehler: HTTP ${r.status}`)
  }

  async function toggleInternet(user, enabled) {
    const r = await api(`/api/accounts/${encodeURIComponent(user)}/internet`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
    if (r.ok) {
      setMsg(`Internet fuer ${user}: ${enabled ? 'an' : 'aus'}.`)
      setConfig(await (await api('/api/config')).json())
    } else setMsg(`Fehler: HTTP ${r.status}`)
  }

  function startEdit(user) {
    setEditUser(user)
    setForm(formFromAccount(config?.accounts?.[user] || {}))
    setMsg(null)
  }

  async function addUser() {
    const user = newUser
    if (!user) return
    setMsg(null)
    const r = await api(`/api/accounts/${encodeURIComponent(user)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_budget_minutes: null, internet_enabled: true, internet_daily_budget_minutes: null, windows: {} }),
    })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      setMsg(`Fehler: ${d.detail ? JSON.stringify(d.detail) : 'HTTP ' + r.status}`)
      return
    }
    setConfig(await (await api('/api/config')).json())
    setNewUser('')
    setMsg(`Konto ${user} angelegt — Regeln jetzt bearbeiten.`)
    startEdit(user)
    load()
  }

  async function save(user) {
    setMsg(null)
    try {
      const body = {
        daily_budget_minutes: form.daily_budget_minutes === '' ? null : Number(form.daily_budget_minutes),
        internet_enabled: form.internet_enabled,
        internet_daily_budget_minutes: form.internet_daily_budget_minutes === '' ? null : Number(form.internet_daily_budget_minutes),
        windows: parseWindows(form.windowsText),
      }
      const r = await api(`/api/accounts/${encodeURIComponent(user)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail ? JSON.stringify(d.detail) : `HTTP ${r.status}`)
      }
      setConfig(await (await api('/api/config')).json())
      setMsg(`Regeln fuer ${user} gespeichert — Daemon uebernimmt sie ohne Neustart.`)
      setEditUser(null)
      load()
    } catch (e) {
      setMsg(`Fehler: ${e.message}`)
    }
  }

  async function reset(user) {
    if (!confirm(`Regeln fuer ${user} auf Standard zuruecksetzen (unbegrenzt, Internet an, keine Fenster)?`)) return
    setMsg(null)
    const r = await api(`/api/accounts/${encodeURIComponent(user)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_budget_minutes: null, internet_enabled: null, internet_daily_budget_minutes: null, windows: {} }),
    })
    if (!r.ok) {
      setMsg(`Fehler: HTTP ${r.status}`)
      return
    }
    setConfig(await (await api('/api/config')).json())
    setMsg(`Regeln fuer ${user} auf Standard zurueckgesetzt.`)
    if (editUser === user) startEdit(user)
    load()
  }

  async function remove(user) {
    if (!confirm(`Regeln fuer ${user} wirklich entfernen?`)) return
    const r = await api(`/api/accounts/${encodeURIComponent(user)}`, { method: 'DELETE' })
    if (r.ok) {
      setConfig(await (await api('/api/config')).json())
      setMsg(`Regeln fuer ${user} entfernt.`)
      if (editUser === user) setEditUser(null)
      load()
    } else {
      setMsg(`Fehler: HTTP ${r.status}`)
    }
  }

  if (auth === undefined) return <div className="wrap"><h1 className="brand">FamilyPC</h1><p className="meta">lade ...</p></div>
  if (auth === null) return <Login onLogin={handleLogin} err={loginErr} />
  if (error) return <div className="wrap"><h1 className="brand">FamilyPC</h1><p className="err">{error}</p></div>
  if (!status) return <div className="wrap"><h1 className="brand">FamilyPC</h1><p className="meta">lade ...</p></div>

  return (
    <div className="wrap">
      <header className="top">
        <div>
          <h1 className="brand">
            <svg viewBox="0 0 52 82" width="26" height="41" aria-hidden="true" style={{ verticalAlign: '-8px', marginRight: 10 }}>
              <path d="M26,2 L50,12 V38 C50,58 38,72 26,80 C14,72 2,58 2,38 V12 Z" fill="url(#shieldG)" stroke="#BBF7D0" strokeWidth="2"/>
              <path d="M15,40 L23,49 L39,28" fill="none" stroke="#fff" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round"/>
              <defs><linearGradient id="shieldG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#4ADE80"/><stop offset="1" stopColor="#16A34A"/></linearGradient></defs>
            </svg>
            FamilyPC
          </h1>
          <p className="tagline">Nutzungszeiten &amp; Internet-Sperre pro Nutzerkonto</p>
        </div>
        <button className="logout" onClick={handleLogout}>Abmelden ({auth})</button>
      </header>
      <p className="meta">Stand {status.now} · Nutzungstag {status.day} · live via SSE</p>
      {msg && <p className="msg">{msg}</p>}
      <div className="add">
        <select value={newUser} onChange={(e) => setNewUser(e.target.value)}>
          <option value="">— Konto waehlen —</option>
          {users.map((u) => (
            <option key={u} value={u} disabled={!!config?.accounts?.[u]}>
              {u}{config?.accounts?.[u] ? ' (bereits konfiguriert)' : ''}
            </option>
          ))}
        </select>
        <button onClick={addUser} disabled={!newUser}>Konto hinzufuegen</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Konto</th><th>Status</th><th>PC-Restzeit</th><th>Fenster</th><th>Internet</th><th>Internet-Restzeit</th><th></th>
          </tr>
        </thead>
        <tbody>
          {status.accounts.map((a) => (
            <React.Fragment key={a.user}>
              <tr>
                <td data-label="Konto"><b>{a.user}</b>{a.protected && <span className="tag">geschuetzt</span>}</td>
                <td data-label="Status">{a.active ? <span className="tag on">aktiv</span> : <span className="tag">inaktiv</span>}</td>
                <td data-label="PC-Restzeit">{a.pc.exhausted ? <span className="tag off">aufgebraucht</span> : fmtMin(a.pc.remaining_seconds)}
                  {a.pc.budget_minutes ? (
                    <div className="bar" title="Restzeit">
                      <div style={{ width: `${Math.max(0, Math.min(100, (a.pc.remaining_seconds / (a.pc.budget_minutes * 60)) * 100))}%` }} />
                    </div>
                  ) : null}
                  <div className="sub">verbraucht {fmtMin(a.pc.used_seconds)}</div></td>
                <td data-label="Fenster">{!a.window.configured ? '—' : a.window.allowed_now ? `erlaubt bis ${a.window.current_end}` : 'ausserhalb'}
                  {a.window.configured && a.window.today.length > 0 && (
                    <div className="sub">heute: {a.window.today.map((w) => `${w.start}-${w.end}`).join(', ')}</div>
                  )}</td>
                <td data-label="Internet">{a.internet.blocked_now ? <span className="tag off">gesperrt</span> : a.internet.enabled === false ? <span className="tag off">aus</span> : <span className="tag on">an</span>}</td>
                <td data-label="Internet-Restzeit">{fmtMin(a.internet.remaining_seconds)}<div className="sub">verbraucht {fmtMin(a.internet.used_seconds)}</div></td>
                <td data-label="Aktionen">
                  <div className="qa">
                    <button onClick={() => extend(a.user, 15)}>+15</button>
                    <button onClick={() => extend(a.user, 30)}>+30</button>
                    <button onClick={() => extend(a.user, 60)}>+60</button>
                    <button onClick={() => terminateSession(a.user)}>Session beenden</button>
                    <button onClick={() => toggleInternet(a.user, a.internet.enabled === false)}>
                      Internet {a.internet.enabled === false ? 'an' : 'aus'}
                    </button>
                  </div>
                  <div className="qa">
                    <button onClick={() => startEdit(a.user)}>Bearbeiten</button>
                    <button onClick={() => reset(a.user)}>Zuruecksetzen</button>
                    <button onClick={() => remove(a.user)}>Entfernen</button>
                  </div>
                </td>
              </tr>
              {editUser === a.user && (
                <tr className="editrow"><td colSpan={7}>
                  <div className="edit">
                    <label>Tagesbudget (Minuten, leer = unbegrenzt)
                      <input type="number" min="0" value={form.daily_budget_minutes}
                        onChange={(e) => setForm({ ...form, daily_budget_minutes: e.target.value })} />
                    </label>
                    <label className="chk"><input type="checkbox" checked={form.internet_enabled}
                      onChange={(e) => setForm({ ...form, internet_enabled: e.target.checked })} /> Internet an</label>
                    <label>Internet-Tagesbudget (Minuten, leer = unbegrenzt)
                      <input type="number" min="0" value={form.internet_daily_budget_minutes}
                        onChange={(e) => setForm({ ...form, internet_daily_budget_minutes: e.target.value })} />
                    </label>
                    <div className="windows">
                      <div>Nutzungsfenster (HH:MM-HH:MM, mehrere mit Komma):</div>
                      {WOCHENTAGE.map((name, d) => (
                        <label key={d}>{name}
                          <input value={form.windowsText[d] ?? ''} placeholder="z. B. 15:00-19:00"
                            onChange={(e) => setForm({ ...form, windowsText: { ...form.windowsText, [d]: e.target.value } })} />
                        </label>
                      ))}
                    </div>
                    <div>
                      <button onClick={() => save(a.user)}>Speichern</button>{' '}
                      <button onClick={() => setEditUser(null)}>Abbrechen</button>
                    </div>
                  </div>
                </td></tr>
              )}
            </React.Fragment>
          ))}
        </tbody>
      </table>
      <p className="meta">Aenderungen wirken ohne Daemon-Neustart. Panel-Accounts: <code>sudo familypc-panel-admin --config /etc/familypc/config.yaml list</code></p>
    </div>
  )
}
