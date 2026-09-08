import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { login as loginRequest, type UserOut } from '../api/auth'
import { clearSessionTokens } from '../api/client'

interface AuthContextValue {
  user: UserOut | null
  isAuthenticating: boolean
  error: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null)
  const [isAuthenticating, setIsAuthenticating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const login = useCallback(async (username: string, password: string) => {
    setIsAuthenticating(true)
    setError(null)
    try {
      const data = await loginRequest(username, password)
      setUser(data.user)
    } catch {
      setError('Usuario ou senha invalidos.')
      clearSessionTokens()
      setUser(null)
    } finally {
      setIsAuthenticating(false)
    }
  }, [])

  const logout = useCallback(() => {
    clearSessionTokens()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, isAuthenticating, error, login, logout }),
    [user, isAuthenticating, error, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
