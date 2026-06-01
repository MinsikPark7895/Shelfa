const BASE_URL = 'https://shelfa.co.kr'

const getToken = () => localStorage.getItem('access_token')

const authHeaders = () => ({
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${getToken()}`,
})

// 토큰 갱신
const refreshToken = async (): Promise<boolean> => {
  try {
    const res = await fetch(`${BASE_URL}/auth/refresh`, { method: 'POST', credentials: 'include' })
    if (!res.ok) return false
    const data = await res.json()
    localStorage.setItem('access_token', data.access_token)
    return true
  } catch {
    return false
  }
}

// 공통 fetch (토큰 만료 시 자동 갱신)
export const apiFetch = async (path: string, options: RequestInit = {}): Promise<Response> => {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
    credentials: 'include',
  })

  if (res.status === 401) {
    const refreshed = await refreshToken()
    if (refreshed) {
      // 갱신 후 재시도
      return fetch(`${BASE_URL}${path}`, {
        ...options,
        headers: { ...authHeaders(), ...(options.headers || {}) },
        credentials: 'include',
      })
    } else {
      // 갱신 실패 → 로그아웃
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
  }

  return res
}

// 인증 없이 호출하는 fetch
export const publicFetch = async (path: string, options: RequestInit = {}): Promise<Response> => {
  return fetch(`${BASE_URL}${path}`, {
    ...options,
    credentials: 'include',
  })
}
