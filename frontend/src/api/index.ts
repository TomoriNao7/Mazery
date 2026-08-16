import { http } from './http'

/* ---------------- 类型 ---------------- */

export interface ScriptCard {
  id: string
  title: string
  category: string
  scene: string
  player_count: number
  summary?: string | null
  is_saved: number
  text_size: number
  created_at: string
  last_played_at?: string
}

export interface CharL1 {
  id: string
  name: string
  age?: number | string
  gender?: string
  profession?: string
  personality?: string
  identity?: string
  appearance?: string
  background?: string
}

export interface Relationship {
  target?: string
  name?: string
  relation?: string
  description?: string
  [k: string]: unknown
}

export interface CharL2 {
  id: string
  name: string
  identity?: string
  background?: string
  appearance?: string
  personality?: string
  relationships: Relationship[]
  goal?: string
  secrets: string[]
  speaking_style?: string
  knowledge_boundary?: string[]
  is_murderer?: boolean
  murderer_notice?: string
  own_clues?: Clue[]
}

export interface Clue {
  id: string
  name: string
  description: string
  location?: string
}

export interface CharCard {
  id: string
  name: string
  identity?: string
  clues: Clue[]
}

export interface PublicClueItem {
  id: string
  name: string
  location?: string
}

export interface GameMessage {
  id?: number
  act?: number
  role: string
  speaker_name?: string
  content: string
  action_type?: string
  created_at?: string
  /** 运行时串场发言序号（仅前端播放用，非后端字段） */
  __sid?: number
}

export interface GameState {
  game_id: string
  script_id: string
  status: string
  player_char_id?: string
  current_act: number
  act_name: string
  stage: string
  stage_label: string
  round_in_stage: number
  max_rounds?: number | null
  allowed_actions: string[]
  private_sessions: Record<string, { target: string; count: number; closed: boolean }>
  votes: Record<string, string>
  discussion?: {
    active: boolean
    round: number
    max_rounds: number
    pending?: { asker?: string; question?: string } | null
  }
}

export interface DrawCards {
  cards: { card_id: string; index: number }[]
  act: number
}

export interface PrivateSendResult {
  player_message: string
  npc_reply: string
  micro_expression?: string | null
  count: number
  max: number
  remaining: number
  forced_end: boolean
  transition?: Transition | null
}

export interface NpcSpeech {
  role: string
  speaker_name: string
  content: string
  action_type?: string
  reveal_clue_id?: string
}

export interface Transition {
  advanced: boolean
  from_act?: number
  to_act?: number
  stage?: string
  status?: string
  message?: string
  narration?: string
  notifications?: string[]
  npc_speeches?: NpcSpeech[]
  act?: number
  discussion_active?: boolean
  discussion_max_rounds?: number
}

export interface DiscussionPlayerTurn {
  kind: 'answer' | 'question'
  asker?: string
  question?: string
}

export interface DiscussionBatch {
  done: boolean
  npc_messages: NpcSpeech[]
  player_turn: DiscussionPlayerTurn | null
  round: number
  max_rounds: number
  transition?: Transition | null
}

export interface VoteResult {
  player_vote: string
  npc_votes: Record<string, string>
  vote_counts: Record<string, number>
  complete: boolean
  status: string
  advance: Transition
}

export interface RevealResult {
  verdict?: string
  truth_summary?: string
  clue_chain_retrospective?: unknown[]
  missed_details?: unknown[]
  npc_outcomes?: unknown[]
  player_score?: { total?: number; breakdown?: unknown[] }
  grade?: string
  raw?: unknown
}

export interface LlmSettings {
  model: string
  base_url: string
  temperature: number
  max_tokens: number
  api_key_set: boolean
  api_key_masked: string
}

export interface ModelPreset {
  id: string
  name: string
  requires_key: boolean
  default_base_url: string
  models: string[]
}

/* ---------------- 剧本库 ---------------- */

export const api = {
  health: async () => (await http.get('/api/health')).data,

  getLocalScripts: async (): Promise<ScriptCard[]> =>
    (await http.get('/api/scripts/local')).data,
  getHistoryScripts: async (): Promise<ScriptCard[]> =>
    (await http.get('/api/scripts/history')).data,
  saveScript: async (id: string) =>
    (await http.post(`/api/script/${id}/save`)).data,

  getScriptInfo: async (id: string): Promise<ScriptCard> =>
    (await http.get(`/api/script/${id}/info`)).data,
  updateScript: async (id: string, payload: Record<string, unknown>): Promise<ScriptCard> =>
    (await http.post(`/api/script/${id}/update`, payload)).data,
  getScriptCharacters: async (id: string): Promise<{ script_id: string; title: string; characters: CharL1[] }> =>
    (await http.get(`/api/script/${id}/characters`)).data,
  getCharacterDetail: async (id: string, cid: string): Promise<CharL2> =>
    (await http.get(`/api/script/${id}/character/${cid}`)).data,

  generateScript: async (payload: Record<string, unknown>) =>
    (await http.post('/api/script/generate', payload)).data,
  generateCustomScript: async (payload: Record<string, unknown>) =>
    (await http.post('/api/script/generate-custom', payload)).data,

  /* ---------------- 游戏 ---------------- */

  startGame: async (scriptId: string, playerCharId?: string) =>
    (
      await http.post('/api/game/start', {
        script_id: scriptId,
        player_char_id: playerCharId ?? null,
      })
    ).data,

  getGameState: async (gameId: string): Promise<GameState> =>
    (await http.get(`/api/game/${gameId}/state`)).data,
  getGameMessages: async (gameId: string): Promise<GameMessage[]> =>
    (await http.get(`/api/game/${gameId}/messages`)).data,
  getGameClues: async (gameId: string): Promise<Clue[]> =>
    (await http.get(`/api/game/${gameId}/clues`)).data,
  getCharacterCards: async (gameId: string): Promise<{ cards: CharCard[]; public_clues: PublicClueItem[] }> =>
    (await http.get(`/api/game/${gameId}/character-cards`)).data,

  getDraw: async (gameId: string): Promise<DrawCards> =>
    (await http.get(`/api/game/${gameId}/draw`)).data,
  pickDraw: async (gameId: string, cardId: string) =>
    (await http.post(`/api/game/${gameId}/draw/${cardId}`)).data,

  getPrivateHistory: async (gameId: string, npcId: string) =>
    (await http.get(`/api/game/${gameId}/private-chat/${npcId}`)).data,
  endPrivate: async (gameId: string, npcId: string) =>
    (await http.post(`/api/game/${gameId}/private-chat/${npcId}/end`)).data,

  /** 公开一条线索（对应 NPC 发言播放完毕后调用，幂等）。 */
  publicizeClue: async (gameId: string, clueId: string) =>
    (await http.post(`/api/game/${gameId}/clue/${clueId}/public`)).data,
  /** 交换阶段重载时，把已如实发言的线索补标记为公开。 */
  reconcileExchange: async (gameId: string) =>
    (await http.post(`/api/game/${gameId}/exchange/reconcile`)).data,

  /** 轮次制讨论：推进到下一步（取回一批 NPC 发言 + 玩家待办）。 */
  discussionNext: async (gameId: string): Promise<DiscussionBatch> =>
    (await http.post(`/api/game/${gameId}/discussion/next`, {})).data,
  /** 讨论：玩家回答某 NPC 的问题。 */
  discussionAnswer: async (gameId: string, content: string): Promise<DiscussionBatch> =>
    (await http.post(`/api/game/${gameId}/discussion/answer`, { content })).data,
  /** 讨论：玩家在自己轮次提问或发言（可选公开自己的线索）。 */
  discussionAction: async (
    gameId: string,
    content: string,
    targetId?: string,
    clueId?: string,
    reveal?: boolean,
  ): Promise<DiscussionBatch> =>
    (
      await http.post(`/api/game/${gameId}/discussion/action`, {
        content,
        target_id: targetId ?? null,
        clue_id: clueId ?? null,
        reveal: !!reveal,
      })
    ).data,
  /** 讨论：玩家跳过本轮提问。 */
  discussionPass: async (gameId: string): Promise<DiscussionBatch> =>
    (await http.post(`/api/game/${gameId}/discussion/pass`, {})).data,

  advance: async (gameId: string): Promise<Transition> =>
    (await http.post(`/api/game/${gameId}/advance`)).data,
  vote: async (gameId: string, targetCharId: string, actorId?: string): Promise<VoteResult> =>
    (
      await http.post(`/api/game/${gameId}/vote`, {
        target_char_id: targetCharId,
        actor_id: actorId ?? null,
      })
    ).data,
  finishGame: async (gameId: string, saveToLibrary: boolean) =>
    (await http.post(`/api/game/${gameId}/finish`, { save_to_library: saveToLibrary })).data,
  reveal: async (gameId: string): Promise<RevealResult> =>
    (await http.get(`/api/game/${gameId}/reveal`)).data,

  /* ---------------- 设置 ---------------- */

  getSettings: async (): Promise<LlmSettings> => (await http.get('/api/settings/llm')).data,
  saveSettings: async (payload: Record<string, unknown>) =>
    (await http.post('/api/settings/llm', payload)).data,
  getModels: async (): Promise<ModelPreset[]> => (await http.get('/api/settings/models')).data,
}

export default api
