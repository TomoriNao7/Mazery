import { API_BASE } from './http'
import type { Transition } from './index'

export interface ActionPayload {
  action: string
  action_type: string
  actor_id?: string | null
  target_id?: string | null
  clue_id?: string | null
}

export interface PrivateChatMeta {
  count: number
  max: number
  remaining: number
  forced_end: boolean
  transition: Transition | null
}

type SseData = Record<string, any>

async function consumeSse(
  resp: Response,
  handle: (data: SseData) => void,
): Promise<void> {
  const reader = resp.body!.getReader()
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
        handle(JSON.parse(line.slice(6)))
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
  await consumeSse(resp, (data) => {
    if (data.chunk) onChunk(data.chunk)
    else if (data.transition) onTransition(data.transition)
    else if (data.error) onError(data.error)
    else if (data.warning) onError(data.warning)
    else if (data.done) onDone()
  })
  onDone()
}

/**
 * 私聊回复：POST 到 /api/game/{id}/private-chat/{npcId}/send，消费 SSE 流。
 * onChunk: 每段 NPC 回复文本；onMeta: 最终计数/强制结束/转场；onDone: 流结束。
 */
export async function streamPrivateChat(
  gameId: string,
  npcId: string,
  content: string,
  onChunk: (text: string) => void,
  onMeta: (meta: PrivateChatMeta) => void,
  onDone: () => void,
  onError: (msg: string) => void,
): Promise<void> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}/api/game/${gameId}/private-chat/${npcId}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
  } catch (e) {
    onError((e as Error).message || '网络错误')
    return
  }
  if (!resp.ok || !resp.body) {
    onError(`请求失败 (${resp.status})`)
    return
  }
  await consumeSse(resp, (data) => {
    if (data.chunk) onChunk(data.chunk)
    else if (data.meta) onMeta(data.meta)
    else if (data.error) onError(data.error)
    else if (data.warning) onError(data.warning)
    else if (data.done) onDone()
  })
  onDone()
}
