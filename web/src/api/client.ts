const API_ROOT = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
const API_BASE_URL = `${API_ROOT}/api/v1`

let accessToken: string | null = null
let refreshToken: string | null = null

export function setSessionTokens(next: { accessToken: string; refreshToken: string }) {
  accessToken = next.accessToken
  refreshToken = next.refreshToken
}

export function clearSessionTokens() {
  accessToken = null
  refreshToken = null
}

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshToken) return false
  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!response.ok) {
    clearSessionTokens()
    return false
  }
  const data = await response.json()
  setSessionTokens({ accessToken: data.access_token, refreshToken: data.refresh_token })
  return true
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isFormData = init.body instanceof FormData

  const doFetch = () =>
    fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...init.headers,
      },
    })

  let response = await doFetch()

  if (response.status === 401 && refreshToken) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      response = await doFetch()
    }
  }

  if (!response.ok) {
    const body = await response.text()
    let message = body
    try {
      const parsed = JSON.parse(body)
      message = parsed?.error?.message ?? body
    } catch {
      // resposta nao era JSON, mantem o texto bruto
    }
    throw new Error(message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

/**
 * Header opcional para correlacionar duas chamadas (ex: uma acao e o anexo de
 * foto enviado logo em seguida) sob o mesmo request_id no historico da API.
 */
export function requestIdHeader(requestId?: string): Record<string, string> {
  return requestId ? { 'X-Request-ID': requestId } : {}
}

/**
 * crypto.randomUUID() exige contexto seguro (HTTPS ou localhost) - no celular,
 * testando via IP da rede local em HTTP puro, ele nao existe e quebra a acao
 * inteira silenciosamente. Gera um id compativel sem depender da Web Crypto API.
 */
export function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return crypto.randomUUID()
    } catch {
      // cai no fallback abaixo
    }
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0
    const value = char === 'x' ? random : (random & 0x3) | 0x8
    return value.toString(16)
  })
}

export async function apiFetchBlob(path: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  })
  if (!response.ok) {
    throw new Error(`Falha ao baixar arquivo (${response.status}).`)
  }
  return response.blob()
}
