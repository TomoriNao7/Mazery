import { API_BASE } from './http'
import type { Transition } from './index'

export interface ActionPayload {
  action: string
  action_type: string
  actor_id?: string | null
  target_id?: string | null
  clue_id?: string | null
}

/**
 * 玩家行动：POST 到 /api/game/{id}/action，消费 SSE 流。
 * onChunk: 每段 GM 流式文本；onTransition: 阶段/幕推进；onDone: 流结束。
 */
export async function streamAction(
  gameId: string,
  payload: ActionPayload,
  onChunk: (text: string) => void,
  onTransition: (t: Transition) => void,
  onDone: () => void,
  onError: (msg: string) => void,
): Promise<void> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}/api/game/${gameId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch (e) {
    onError((e as Error).message || '网络错误')
    return
  }
  if (!resp.ok || !resp.body) {
    onError(`请求失败 (${resp.status})`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  const flush = () => {
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = raw.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.chunk) onChunk(data.chunk)
        else if (data.transition) onTransition(data.transition)
        else if (data.error) onError(data.error)
        else if (data.warning) onError(data.warning)
        else if (data.done) onDone()
      } catch {
        /* 忽略无法解析的事件 */
      }
    }
  }

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    flush()
  }
  buf += decoder.decode()
  flush()
  onDone()
}
