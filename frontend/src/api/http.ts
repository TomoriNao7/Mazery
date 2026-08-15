import axios from 'axios'

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string) || 'http://localhost:18920'

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg =
      err?.response?.data?.detail || err?.response?.data?.message || err?.message || '网络错误'
    return Promise.reject(new Error(msg))
  },
)
