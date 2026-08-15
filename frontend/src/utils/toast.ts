import { reactive } from 'vue'

export interface ToastItem {
  id: number
  text: string
  type: 'info' | 'success' | 'error'
}

let seq = 0
export const toasts = reactive<ToastItem[]>([])

export function toast(text: string, type: ToastItem['type'] = 'info', duration = 2600) {
  const id = ++seq
  toasts.push({ id, text, type })
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i !== -1) toasts.splice(i, 1)
  }, duration)
}
