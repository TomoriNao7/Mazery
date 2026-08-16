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
  relationships: Relationship[]
  goal?: unknown
  secrets: unknown[]
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

export interface GameMessage {
  id?: number
  act?: number
  role: string
  speaker_name?: string
  content: string
  action_type?: string
  created_at?: string
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

export interface Transition {
  advanced: boolean
  from_act?: number
  to_act?: number
  stage?: string
  status?: string
  message?: string
  narration?: string
  notifications?: string[]
  act?: number
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
  getCharacterCards: async (gameId: string): Promise<{ cards: CharCard[] }> =>
    (await http.get(`/api/game/${gameId}/character-cards`)).data,

  getDraw: async (gameId: string): Promise<DrawCards> =>
    (await http.get(`/api/game/${gameId}/draw`)).data,
  pickDraw: async (gameId: string, cardId: string) =>
    (await http.post(`/api/game/${gameId}/draw/${cardId}`)).data,

  getPrivateHistory: async (gameId: string, npcId: string) =>
    (await http.get(`/api/game/${gameId}/private-chat/${npcId}`)).data,
  endPrivate: async (gameId: string, npcId: string) =>
    (await http.post(`/api/game/${gameId}/private-chat/${npcId}/end`)).data,

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
