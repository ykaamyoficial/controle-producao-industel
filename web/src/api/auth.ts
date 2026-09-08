import { apiFetch, setSessionTokens } from './client'

export interface RoleOut {
  id: number
  code: string
  name: string
  active: boolean
}

export interface UserOut {
  id: number
  username: string
  display_name: string
  active: boolean
  is_superuser: boolean
  password_must_change: boolean
  roles: RoleOut[]
  permissions: string[]
}

interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserOut
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const data = await apiFetch<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  setSessionTokens({ accessToken: data.access_token, refreshToken: data.refresh_token })
  return data
}

export async function fetchMe(): Promise<UserOut> {
  return apiFetch<UserOut>('/auth/me')
}

export async function logout(refreshToken: string): Promise<void> {
  await apiFetch<void>('/auth/logout', {
    method: 'POST',
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
}
