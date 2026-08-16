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
  type NpcSpeech,
  type DiscussionBatch,
} from '../api'
import { streamAction, streamPrivateChat, type ActionPayload, type PrivateChatMeta } from '../api/sse'

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// 运行时发言序号（每局自增，用于标记正在打字的消息）
let speechSeq = 0

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
    publicClues: [] as { id: string; name: string }[],

    typing: false,
    partial: '',
    error: '',
    lastTransition: null as Transition | null,
    pendingNotifications: [] as string[],

    // 阶段自发言串场播放队列（intro/exchange：直接往正式消息逐字打字 + 句间 1s；GM 淡入）
    speechQueue: [] as NpcSpeech[],
    speaking: false,
    typingSpeechSid: null as number | null,
    speechTick: 0,
    speechLastPlayedId: 0,

    // 轮次制讨论状态
    discussion: {
      active: false,
      needStart: false,
      round: 1,
      maxRounds: 0,
      playerInput: null as 'answer' | 'question' | null,
      pendingAsker: '',
      pendingQuestion: '',
      busy: false,
    },
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

    /** 统一处理阶段/幕转场：更新状态、追加 GM 旁白、入队 NPC 自发言、幕间通知。 */
    _applyTransition(t: Transition) {
      if (!t) return
      if (t.stage) this.stage = t.stage
      if (t.to_act) this.currentAct = t.to_act
      if (t.status) this.status = t.status
      this.lastTransition = t
      // 幕间通知仅在新一幕时弹出（后端已对同幕阶段转场清空 notifications）
      if (t.notifications?.length) this.pendingNotifications = t.notifications
      const narration = (t.narration || '').trim()
      if (narration) {
        this.messages.push({
          role: 'system', speaker_name: 'GM', content: narration, action_type: 'narration',
        })
      }
      // NPC 自发言不直接落盘显示，进串场播放队列（逐句 + 1s 间隔）
      if (t.npc_speeches?.length) {
        this.speechQueue.push(...t.npc_speeches)
      }
      // 进入讨论阶段：标记待启动（队列播完或当前无队列时触发 /discussion/next）
      if (t.discussion_active) {
        this.discussion.active = true
        this.discussion.maxRounds = t.discussion_max_rounds ?? this.discussion.maxRounds
        this.discussion.needStart = true
        this.discussion.playerInput = null
      }
      void this.playSpeechQueue()
      void this._maybeStartDiscussion()
    },

    /** 讨论阶段首次启动：等串场队列播完后再调 /discussion/next。 */
    async _maybeStartDiscussion() {
      if (!this.discussion.active || !this.discussion.needStart) return
      if (this.speaking) return // 队列还在播，播完由 playSpeechQueue 触发
      this.discussion.needStart = false
      await this.discussionStep()
    },

    /** 应用讨论批次：入队 NPC 发言 + 更新玩家待办；done 时应用转场。 */
    _applyDiscussion(res: DiscussionBatch) {
      this.discussion.round = res.round
      this.discussion.maxRounds = res.max_rounds
      if (res.npc_messages?.length) {
        this.speechQueue.push(...res.npc_messages)
      }
      if (res.done) {
        this.discussion.active = false
        this.discussion.playerInput = null
        this.discussion.needStart = false
        if (res.transition) this._applyTransition(res.transition)
      } else if (res.player_turn) {
        this.discussion.playerInput = res.player_turn.kind
        this.discussion.pendingAsker = res.player_turn.asker || ''
        this.discussion.pendingQuestion = res.player_turn.question || ''
      }
      void this.playSpeechQueue()
    },

    async discussionStep() {
      if (this.discussion.busy) return
      this.discussion.busy = true
      try {
        const res = await api.discussionNext(this.gameId)
        this._applyDiscussion(res)
      } catch (e) {
        this.error = (e as Error).message
        this.discussion.needStart = false
      } finally {
        this.discussion.busy = false
      }
    },
    async discussionAnswer(content: string) {
      if (this.discussion.busy) return
      this.discussion.busy = true
      try {
        const res = await api.discussionAnswer(this.gameId, content)
        this._applyDiscussion(res)
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.discussion.busy = false
      }
    },
    async discussionAction(content: string, target?: string, clueId?: string, reveal?: boolean) {
      if (this.discussion.busy) return
      this.discussion.busy = true
      try {
        const res = await api.discussionAction(this.gameId, content, target, clueId, reveal)
        this._applyDiscussion(res)
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.discussion.busy = false
      }
    },
    async discussionPass() {
      if (this.discussion.busy) return
      this.discussion.busy = true
      try {
        const res = await api.discussionPass(this.gameId)
        this._applyDiscussion(res)
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.discussion.busy = false
      }
    },

    async init(gameId: string) {
      this.gameId = gameId
      this.error = ''
      const st = await api.getGameState(gameId)
      this.applyState(st)
      // 交换阶段重载：先把已如实发言的线索补公开，再拉人物卡/公开列表，保证一致
      if (this.stage === 'exchange') {
        try {
          await api.reconcileExchange(this.gameId)
        } catch {
          /* ignore */
        }
      }
      const [messages, clues, cardsRes] = await Promise.all([
        api.getGameMessages(gameId),
        api.getGameClues(gameId),
        api.getCharacterCards(gameId),
      ])
      // 恢复已播放进度：仅把未播放的阶段自发言放入串场队列
      const key = this._speechKey()
      const saved = Number(localStorage.getItem(key) || 0)
      this.speechLastPlayedId = Number.isFinite(saved) ? saved : 0
      const pending = messages.filter(
        (m) => m.action_type === 'stage_speech' && (m.id ?? 0) > this.speechLastPlayedId,
      ).map((m) => ({
        role: m.role,
        speaker_name: m.speaker_name || '',
        content: m.content,
        action_type: m.action_type,
      }))
      this.messages = messages.filter((m) => m.action_type !== 'stage_speech' || (m.id ?? 0) <= this.speechLastPlayedId)
      this.foundClues = clues
      this.characterCards = cardsRes.cards
      this.publicClues = cardsRes.public_clues || []
      if (this.scriptId && !this.characters.length) {
        try {
          const res = await api.getScriptCharacters(this.scriptId)
          this.characters = res.characters
        } catch {
          /* ignore */
        }
      }
      if (pending.length) {
        this.speechQueue.push(...pending)
        void this.playSpeechQueue()
      }
      // 讨论中途重载：恢复讨论状态，续取下一批（等队列播完再触发）
      if (st.discussion?.active) {
        this.discussion.active = true
        this.discussion.maxRounds = st.discussion.max_rounds ?? this.discussion.maxRounds
        this.discussion.round = st.discussion.round ?? 1
        this.discussion.needStart = true
        this.discussion.playerInput = null
        this.discussion.pendingAsker = st.discussion.pending?.asker || ''
        this.discussion.pendingQuestion = st.discussion.pending?.question || ''
        void this._maybeStartDiscussion()
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
      this.publicClues = cardsRes.public_clues || []
      this.foundClues = clues
    },

    /** 串场播放：把发言直接逐字打进正式消息（一句一条消息），句间 1s、GM 淡入；
        如实发言结束后公开对应线索。 */
    async playSpeechQueue() {
      if (this.speaking || !this.speechQueue.length) return
      this.speaking = true
      while (this.speechQueue.length) {
        const sp = this.speechQueue.shift()!
        const isGM = sp.role === 'system' || sp.role === 'narrator'
        speechSeq += 1
        const sid = speechSeq
        this.messages.push({
          role: sp.role,
          speaker_name: sp.speaker_name,
          content: '',
          action_type: sp.action_type || 'dialogue',
          __sid: sid,
        })
        const idx = this.messages.length - 1
        if (isGM) {
          this.messages[idx] = { ...this.messages[idx], content: sp.content }
          await delay(1400)
        } else {
          this.typingSpeechSid = sid
          const content = sp.content
          for (let i = 0; i < content.length; i += 2) {
            this.messages[idx] = { ...this.messages[idx], content: content.slice(0, i + 2) }
            this.speechTick += 1
            await delay(24)
          }
          this.messages[idx] = { ...this.messages[idx], content }
          this.speechTick += 1
          this.typingSpeechSid = null
          await delay(450)
        }
        // 如实发言结束后公开这条线索（人物卡 + 公开列表刷新）
        if (sp.reveal_clue_id) {
          try {
            await api.publicizeClue(this.gameId, sp.reveal_clue_id)
          } catch {
            /* ignore */
          }
          await this.refresh()
        }
        if (this.speechQueue.length) await delay(1000)
      }
      this.speaking = false
      // 用 DB 中的真实消息 id 记录播放进度，避免重载后重复播放
      try {
        const msgs = await api.getGameMessages(this.gameId)
        const maxId = msgs.reduce((m, x) => Math.max(m, x.id ?? 0), 0)
        if (maxId > this.speechLastPlayedId) {
          this.speechLastPlayedId = maxId
          localStorage.setItem(this._speechKey(), String(maxId))
        }
      } catch {
        /* ignore */
      }
      // 队列播完：若讨论阶段待启动，触发下一轮讨论
      await this._maybeStartDiscussion()
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
      if (this.typing || this.speaking) return
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
        this._applyTransition(t)
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
      this._applyTransition(t)
      await this.refresh()
      return t
    },
    /** 私聊发送（SSE 流式）：onChunk 逐段回调，返回最终计数/强制结束/转场。 */
    async sendPrivate(
      npcId: string,
      content: string,
      onChunk?: (t: string) => void,
    ): Promise<PrivateSendResult> {
      let reply = ''
      let meta: PrivateChatMeta = { count: 0, max: 0, remaining: 0, forced_end: false, transition: null }
      const onMeta = (m: PrivateChatMeta) => {
        meta = m
        if (m.transition) this._applyTransition(m.transition)
      }
      const onError = (m: string) => {
        this.error = m
      }
      await streamPrivateChat(
        this.gameId, npcId, content,
        (t) => {
          reply += t
          onChunk?.(t)
        },
        onMeta,
        () => {},
        onError,
      )
      await this.refresh()
      return {
        player_message: content,
        npc_reply: reply,
        count: meta.count,
        max: meta.max,
        remaining: meta.remaining,
        forced_end: meta.forced_end,
        transition: meta.transition,
      }
    },
    async endPrivate(npcId: string) {
      const res = await api.endPrivate(this.gameId, npcId)
      if (res.transition) this._applyTransition(res.transition)
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
      this.publicClues = []
      this.typing = false
      this.partial = ''
      this.error = ''
      this.lastTransition = null
      this.pendingNotifications = []
      this.speechQueue = []
      this.speaking = false
      this.typingSpeechSid = null
      this.speechTick = 0
      this.speechLastPlayedId = 0
      this.discussion = {
        active: false, needStart: false, round: 1, maxRounds: 0,
        playerInput: null, pendingAsker: '', pendingQuestion: '', busy: false,
      }
    },

    /** 每局独立的播放进度 key（localStorage）。 */
    _speechKey(): string {
      return this.gameId ? `mazery_speech_${this.gameId}` : 'mazery_speech'
    },
  },
})
