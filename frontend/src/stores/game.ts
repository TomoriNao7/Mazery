import { defineStore } from 'pinia'
import api, {
  type GameMessage,
  type GameState,
  type CharL1,
  type Clue,
  type CharCard,
  type Transition,
  type DrawCards,
  type PrivateSendResult,
} from '../api'
import { streamAction, type ActionPayload } from '../api/sse'

export const useGameStore = defineStore('game', {
  state: () => ({
    gameId: '',
    scriptId: '',
    playerCharId: '',
    status: 'playing',
    currentAct: 1,
    actName: '',
    stage: '',
    stageLabel: '',
    roundInStage: 0,
    maxRounds: null as number | null,
    allowedActions: [] as string[],
    privateSessions: {} as Record<string, { target: string; count: number; closed: boolean }>,
    votes: {} as Record<string, string>,

    characters: [] as CharL1[],
    messages: [] as GameMessage[],
    foundClues: [] as Clue[],
    characterCards: [] as CharCard[],

    typing: false,
    partial: '',
    error: '',
    lastTransition: null as Transition | null,
    pendingNotifications: [] as string[],
  }),

  getters: {
    npcName: (s) => (id: string) => s.characters.find((c) => c.id === id)?.name || id,
    myName: (s) =>
      s.playerCharId
        ? s.characters.find((c) => c.id === s.playerCharId)?.name || s.playerCharId
        : '你',
    charById: (s) => (id: string) => s.characters.find((c) => c.id === id) || null,
  },

  actions: {
    applyState(st: GameState) {
      this.gameId = st.game_id
      this.scriptId = st.script_id
      this.playerCharId = st.player_char_id || ''
      this.status = st.status
      this.currentAct = st.current_act
      this.actName = st.act_name
      this.stage = st.stage
      this.stageLabel = st.stage_label
      this.roundInStage = st.round_in_stage
      this.maxRounds = st.max_rounds ?? null
      this.allowedActions = st.allowed_actions
      this.privateSessions = st.private_sessions || {}
      this.votes = st.votes || {}
    },

    async init(gameId: string) {
      this.gameId = gameId
      this.error = ''
      const st = await api.getGameState(gameId)
      this.applyState(st)
      const [messages, clues, cardsRes] = await Promise.all([
        api.getGameMessages(gameId),
        api.getGameClues(gameId),
        api.getCharacterCards(gameId),
      ])
      this.messages = messages
      this.foundClues = clues
      this.characterCards = cardsRes.cards
      if (this.scriptId && !this.characters.length) {
        try {
          const res = await api.getScriptCharacters(this.scriptId)
          this.characters = res.characters
        } catch {
          /* ignore */
        }
      }
    },

    async refresh() {
      if (!this.gameId) return
      const st = await api.getGameState(this.gameId)
      this.applyState(st)
      const [cardsRes, clues] = await Promise.all([
        api.getCharacterCards(this.gameId),
        api.getGameClues(this.gameId),
      ])
      this.characterCards = cardsRes.cards
      this.foundClues = clues
    },

    commitPartial() {
      const text = this.partial.trim()
      if (text) {
        this.messages.push({
          role: 'system',
          speaker_name: 'GM',
          content: text,
          action_type: 'narration',
        })
      }
      this.partial = ''
    },

    /** 主聊天行动（SSE 流式）：发言/提问/介绍线索等。 */
    async sendAction(payload: ActionPayload) {
      if (this.typing) return
      this.error = ''
      this.typing = true
      this.partial = ''

      this.messages.push({
        role: 'player',
        speaker_name: payload.actor_id || this.playerCharId || 'player',
        content: payload.action,
        action_type: payload.action_type,
      })

      const onChunk = (t: string) => {
        this.partial += t
      }
      const onTransition = (t: Transition) => {
        this.commitPartial()
        if (t.stage) this.stage = t.stage
        if (t.to_act) this.currentAct = t.to_act
        if (t.status) this.status = t.status
        this.lastTransition = t
        if (t.notifications?.length) this.pendingNotifications = t.notifications
        const narration = (t.narration || '').trim()
        if (narration) {
          this.messages.push({
            role: 'system',
            speaker_name: 'GM',
            content: narration,
            action_type: 'narration',
          })
        }
      }
      const onDone = () => {
        this.commitPartial()
        this.typing = false
        void this.refresh()
      }
      const onError = (m: string) => {
        this.error = m
        this.commitPartial()
        this.typing = false
      }

      await streamAction(this.gameId, payload, onChunk, onTransition, onDone, onError)
    },

    async getDraw(): Promise<DrawCards> {
      const res = await api.getDraw(this.gameId)
      return res
    },
    async pickDraw(cardId: string) {
      const res = await api.pickDraw(this.gameId, cardId)
      await this.refresh()
      return res
    },
    async advanceNow(): Promise<Transition> {
      const t = await api.advance(this.gameId)
      this.lastTransition = t
      if (t.stage) this.stage = t.stage
      if (t.to_act) this.currentAct = t.to_act
      if (t.status) this.status = t.status
      if (t.notifications?.length) this.pendingNotifications = t.notifications
      const narration = (t.narration || '').trim()
      if (narration) {
        this.messages.push({ role: 'system', speaker_name: 'GM', content: narration, action_type: 'narration' })
      }
      await this.refresh()
      return t
    },
    async sendPrivate(npcId: string, content: string): Promise<PrivateSendResult> {
      const res = await api.sendPrivate(this.gameId, npcId, content)
      await this.refresh()
      return res
    },
    async endPrivate(npcId: string) {
      const res = await api.endPrivate(this.gameId, npcId)
      if (res.transition) {
        this.lastTransition = res.transition
        if (res.transition.stage) this.stage = res.transition.stage
        if (res.transition.to_act) this.currentAct = res.transition.to_act
        if (res.transition.notifications?.length) this.pendingNotifications = res.transition.notifications
      }
      await this.refresh()
      return res
    },
    async voteNow(targetCharId: string) {
      const res = await api.vote(this.gameId, targetCharId, this.playerCharId)
      await this.refresh()
      return res
    },
    async finish(saveToLibrary: boolean) {
      return api.finishGame(this.gameId, saveToLibrary)
    },

    dismissNotifications() {
      this.pendingNotifications = []
    },
    reset() {
      this.gameId = ''
      this.messages = []
      this.characters = []
      this.foundClues = []
      this.characterCards = []
      this.typing = false
      this.partial = ''
      this.error = ''
      this.lastTransition = null
      this.pendingNotifications = []
    },
  },
})
