import axios from 'axios'

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string) || 'http://localhost:18920'

export const http = axios.create({
  baseURL: API_BASE,
  // 剧本生成是多次串行 LLM 调用，可能数分钟；超时放宽到 10 分钟避免中途掐断
  timeout: 600000,
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
