import React, { useCallback, useEffect, useState } from 'react'

const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

function fmtMin(sec) {
  if (sec === null || sec === undefined) return 'unbegrenzt'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m} min ${s > 0 ? `${s} s` : ''}`.trim() : `${s} s`
}

function parseWindows(textByDay) {
  // textByDay: {0: "15:00-19:00, 20:00-21:00", ...} -> {0: [{start,end}], ...}
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

export default function App() {
  const [status, setStatus] = useState(null)
  const [config, setConfig] = useState(null)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [editUser, setEditUser] = useState(null)
  const [form, setForm] = useState(emptyForm())
  const [newUser, setNewUser] = useState('')
  const [users, setUsers] = useState([])

  useEffect(() => {
    fetch('/api/users').then((r) => r.json()).then((d) => setUsers(d.users || [])).catch(() => {})
  }, [])

  async function addUser() {
    const user = newUser.trim()
    if (!user) return
    setMsg(null)
    const r = await fetch(`/api/accounts/${encodeURIComponent(user)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_budget_minutes: null, internet_enabled: true, internet_daily_budget_minutes: null, windows: {} }),
    })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      setMsg(`Fehler: ${d.detail ? JSON.stringify(d.detail) : 'HTTP ' + r.status}`)
      return
    }
    setConfig(await (await fetch('/api/config')).json())
    setNewUser('')
    setMsg(`Konto ${user} angelegt — Regeln jetzt bearbeiten.`)
    startEdit(user)
    load()
  }

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([fetch('/api/status'), fetch('/api/config')])
      if (s.status === 403 || c.status === 403) {
        setError('Zugriff nur aus Admin-Sitzung (sudo-Gruppe) moeglich.')
        return
      }
      setStatus(await s.json())
      setConfig(await c.json())
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])

  function startEdit(user) {
    setEditUser(user)
    setForm(formFromAccount(config?.accounts?.[user] || {}))
    setMsg(null)
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
      const r = await fetch(`/api/accounts/${encodeURIComponent(user)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail ? JSON.stringify(d.detail) : `HTTP ${r.status}`)
      }
      setConfig(await (await fetch('/api/config')).json())
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
    const r = await fetch(`/api/accounts/${encodeURIComponent(user)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_budget_minutes: null, internet_enabled: null, internet_daily_budget_minutes: null, windows: {} }),
    })
    if (!r.ok) {
      setMsg(`Fehler: HTTP ${r.status}`)
      return
    }
    setConfig(await (await fetch('/api/config')).json())
    setMsg(`Regeln fuer ${user} auf Standard zurueckgesetzt.`)
    if (editUser === user) startEdit(user)
    load()
  }

  async function remove(user) {
    if (!confirm(`Regeln fuer ${user} wirklich entfernen?`)) return
    const r = await fetch(`/api/accounts/${encodeURIComponent(user)}`, { method: 'DELETE' })
    if (r.ok) {
      setConfig(await (await fetch('/api/config')).json())
      setMsg(`Regeln fuer ${user} entfernt.`)
      if (editUser === user) setEditUser(null)
      load()
    } else {
      setMsg(`Fehler: HTTP ${r.status}`)
    }
  }

  if (error) return <div className="wrap"><h1>FamilyPC Admin</h1><p className="err">{error}</p></div>
  if (!status) return <div className="wrap"><h1>FamilyPC Admin</h1><p>lade ...</p></div>

  return (
    <div className="wrap">
      <h1>FamilyPC Admin</h1>
      <p className="meta">Stand {status.now} · Nutzungstag {status.day} · aktualisiert alle 5 s</p>
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
                <td><b>{a.user}</b>{a.protected && <span className="tag">geschuetzt</span>}</td>
                <td>{a.active ? <span className="tag on">aktiv</span> : <span className="tag">inaktiv</span>}</td>
                <td>{a.pc.exhausted ? <span className="tag off">aufgebraucht</span> : fmtMin(a.pc.remaining_seconds)}
                  <div className="sub">verbraucht {fmtMin(a.pc.used_seconds)}</div></td>
                <td>{!a.window.configured ? '—' : a.window.allowed_now ? `erlaubt bis ${a.window.current_end}` : 'ausserhalb'}
                  {a.window.configured && a.window.today.length > 0 && (
                    <div className="sub">heute: {a.window.today.map((w) => `${w.start}-${w.end}`).join(', ')}</div>
                  )}</td>
                <td>{a.internet.blocked_now ? <span className="tag off">gesperrt</span> : a.internet.enabled === false ? <span className="tag off">aus</span> : <span className="tag on">an</span>}</td>
                <td>{fmtMin(a.internet.remaining_seconds)}<div className="sub">verbraucht {fmtMin(a.internet.used_seconds)}</div></td>
                <td><button onClick={() => startEdit(a.user)}>Bearbeiten</button>{' '}
                  <button onClick={() => reset(a.user)}>Zuruecksetzen</button>{' '}
                  <button onClick={() => remove(a.user)}>Entfernen</button></td>
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
      <p className="meta">Aenderungen wirken ohne Daemon-Neustart. Nur lokal erreichbar (127.0.0.1).</p>
    </div>
  )
}
