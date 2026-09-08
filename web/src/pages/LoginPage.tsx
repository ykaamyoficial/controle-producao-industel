import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { user, isAuthenticating, error, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  if (user) return <Navigate to="/" replace />

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    await login(username, password)
  }

  return (
    <div className="flex min-h-svh flex-col justify-center gap-6 bg-slate-950 px-6 text-slate-100">
      <h1 className="text-2xl font-semibold">Controle de Producao</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <input
          className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-base"
          placeholder="Usuario"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
        />
        <input
          className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-base"
          placeholder="Senha"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={isAuthenticating}
          className="rounded-lg bg-sky-500 py-3 text-base font-medium text-slate-950 disabled:opacity-60"
        >
          {isAuthenticating ? 'Entrando...' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}
