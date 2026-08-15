<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api, { type CharL1, type CharCard, type RevealResult } from '../api'
import { useGameStore } from '../stores/game'
import DrawModal from '../components/DrawModal.vue'
import PrivateChatModal from '../components/PrivateChatModal.vue'
import VoteModal from '../components/VoteModal.vue'
import RevealModal from '../components/RevealModal.vue'
import CharacterDetailModal from '../components/CharacterDetailModal.vue'
import NotifyModal from '../components/NotifyModal.vue'
import { toast } from '../utils/toast'

const route = useRoute()
const router = useRouter()
const gameId = route.params.id as string
const game = useGameStore()

const loading = ref(true)
const error = ref('')
const scriptTitle = ref('')

const showDraw = ref(false)
const showVote = ref(false)
const showReveal = ref(false)
const revealData = ref<RevealResult | null>(null)
const showPrivate = ref(false)
const privateNpc = ref('')
const showCharDetail = ref(false)
const charDetailChar = ref<CharL1 | null>(null)
const charDetailCard = ref<CharCard | null>(null)
const notifyShow = ref(false)

const input = ref('')
const selectedTarget = ref('')
const selectedClue = ref('')

const chatBody = ref<HTMLElement | null>(null)

/* ---------- 派生 ---------- */

const stage = computed(() => game.stage)

const mode = computed(() => {
  const s = stage.value
  if (s === 'intro_r1') return 'introduce'
  if (s === 'intro_r2') return 'question'
  if (s === 'exchange') return game.roundInStage === 0 ? 'introduce_clue' : 'question'
  if (s === 'public') return 'talk'
  if (s === 'draw' || s === 'private' || s === 'vote') return 'disabled'
  return 'talk'
})

const targets = computed(() => game.characters.filter((c) => c.id !== game.playerCharId))

const clueOptions = computed(() => [
  ...game.foundClues.map((c) => ({ value: c.id, label: c.name })),
  { value: 'none', label: '隐瞒 / 编造（不展示真实线索）' },
])

const chatMessages = computed(() =>
  game.messages.filter((m) => m.action_type !== 'private_chat'),
)

const myTarget = computed(() =>
  game.playerCharId ? game.privateSessions[game.playerCharId]?.target : undefined,
)
const sessionClosed = computed(() =>
  game.playerCharId ? game.privateSessions[game.playerCharId]?.closed : false,
)

const publicClues = computed(() => {
  const seen = new Map<string, { id: string; name: string }>()
  for (const card of game.characterCards) {
    for (const c of card.clues) {
      if (!seen.has(c.id)) seen.set(c.id, { id: c.id, name: c.name })
    }
  }
  return Array.from(seen.values())
})

const placeholder = computed(() => {
  switch (mode.value) {
    case 'introduce':
      return '自我介绍…'
    case 'introduce_clue':
      return '介绍你拿到的线索，或隐瞒、或编造…'
    case 'question':
      return '向对方提问…'
    case 'talk':
      return '发言…'
    default:
      return ''
  }
})

function charClues(id: string) {
  return game.characterCards.find((c) => c.id === id)?.clues || []
}

function findCharOf(clueId: string): CharL1 | null {
  for (const card of game.characterCards) {
    if (card.clues.some((c) => c.id === clueId)) {
      return game.characters.find((c) => c.id === card.id) || null
    }
  }
  return null
}

function isSystem(m: { role: string }): boolean {
  return m.role === 'system' || m.role === 'narrator'
}

function privateEnabled(npcId: string): boolean {
  if (stage.value !== 'private') return false
  if (!myTarget.value) return true
  if (sessionClosed.value) return false
  return myTarget.value === npcId
}

/* ---------- 阶段驱动 ---------- */

function handleStage(st: string) {
  showDraw.value = st === 'draw'
  showVote.value = st === 'vote'
}

async function openReveal() {
  try {
    revealData.value = await api.reveal(gameId)
    showReveal.value = true
  } catch (e) {
    toast((e as Error).message, 'error')
  }
}

watch(stage, (st) => handleStage(st))
watch(
  () => game.status,
  (st) => {
    if (st === 'voted') void openReveal()
  },
)
watch(
  () => game.pendingNotifications,
  (n) => {
    if (n && n.length) notifyShow.value = true
  },
)
watch(
  () => [game.messages.length, game.partial],
  async () => {
    await nextTick()
    if (chatBody.value) chatBody.value.scrollTop = chatBody.value.scrollHeight
  },
)

/* ---------- 初始化 ---------- */

onMounted(async () => {
  try {
    await game.init(gameId)
    try {
      const info = await api.getScriptInfo(game.scriptId)
      scriptTitle.value = info.title
    } catch {
      /* ignore */
    }
    handleStage(game.stage)
    if (game.status === 'voted') void openReveal()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})

/* ---------- 交互 ---------- */

function openChar(c: CharL1) {
  charDetailChar.value = c
  charDetailCard.value = game.characterCards.find((x) => x.id === c.id) || null
  showCharDetail.value = true
}

function openPrivate(npcId: string) {
  if (!privateEnabled(npcId)) return
  privateNpc.value = npcId
  showPrivate.value = true
}

async function send() {
  const text = input.value.trim()
  if (!text || game.typing) return
  if (mode.value === 'disabled') return

  const payload: {
    action: string
    action_type: string
    actor_id: string
    target_id: string | null
    clue_id: string | null
  } = {
    action: text,
    action_type: mode.value,
    actor_id: game.playerCharId || 'player',
    target_id: null,
    clue_id: null,
  }

  if (mode.value === 'question') {
    if (!selectedTarget.value) {
      toast('请先选择提问对象', 'error')
      return
    }
    payload.target_id = selectedTarget.value
  }

  if (mode.value === 'introduce_clue') {
    if (selectedClue.value && selectedClue.value !== 'none') {
      payload.clue_id = selectedClue.value
      const c = game.foundClues.find((x) => x.id === selectedClue.value)
      payload.action = text || c?.name || text
    }
  }

  input.value = ''
  selectedTarget.value = ''
  selectedClue.value = ''
  await game.sendAction(payload)
}

async function onRevealSave() {
  try {
    await game.finish(true)
    toast('已保存到本地剧本库', 'success')
  } catch (e) {
    toast((e as Error).message, 'error')
  }
  router.push('/library')
}
async function onRevealExit() {
  try {
    await game.finish(false)
  } catch {
    /* ignore */
  }
  router.push('/library')
}

function leave() {
  router.push('/library')
}
</script>

<template>
  <div class="game">
    <header class="game-top">
      <button class="top-back" @click="leave">← 剧本库</button>
      <div class="top-title display">{{ scriptTitle || '游戏进行中' }}</div>
      <div class="top-badge">
        <span class="badge-act">第 {{ game.currentAct }} 幕 · {{ game.actName }}</span>
        <span class="badge-stage gold">{{ game.stageLabel || game.stage }}</span>
      </div>
    </header>

    <div v-if="loading" class="game-loading">
      <div class="skeleton" style="height: 30px; width: 240px"></div>
      <div class="skeleton" style="height: 400px; width: 100%; margin-top: 18px"></div>
    </div>
    <div v-else-if="error" class="game-error">
      <p class="muted">{{ error }}</p>
      <button class="btn btn-sm" @click="leave">返回剧本库</button>
    </div>
    <div v-else class="game-body">
      <!-- 左栏 -->
      <aside class="game-left">
        <div class="left-title dim">人物</div>
        <div class="char-list">
          <div v-for="c in game.characters" :key="c.id" class="char-row" @click="openChar(c)">
            <div class="chr-avatar">{{ (c.name || '?').slice(0, 1) }}</div>
            <div class="chr-info">
              <div class="chr-name">
                {{ c.name }}
                <span v-if="c.id === game.playerCharId" class="chr-me">(我)</span>
              </div>
              <div class="chr-id dim">{{ c.identity || c.profession || '' }}</div>
              <div v-if="charClues(c.id).length" class="chr-clues">
                <span v-for="cl in charClues(c.id)" :key="cl.id" class="chr-clue">{{ cl.name }}</span>
              </div>
            </div>
            <button
              v-if="stage === 'private'"
              class="btn btn-sm chr-private"
              :class="{ disabled: !privateEnabled(c.id) }"
              @click.stop="openPrivate(c.id)"
            >
              私聊
            </button>
          </div>
        </div>

        <div class="left-title dim" style="margin-top: 20px">已公开线索</div>
        <div v-if="publicClues.length" class="public-list">
          <button
            v-for="cl in publicClues"
            :key="cl.id"
            class="public-item"
            @click="openChar(findCharOf(cl.id) || { id: '', name: '' })"
          >
            <span class="public-dot" />
            {{ cl.name }}
          </button>
        </div>
        <p v-else class="public-empty dim">搜证与交换信息后，公开线索会出现在这里</p>
      </aside>

      <!-- 右栏：聊天 -->
      <main class="game-main">
        <div ref="chatBody" class="chat-body">
          <TransitionGroup name="msg" tag="div" class="chat-list">
            <template v-for="(m, i) in chatMessages" :key="i">
              <div v-if="isSystem(m)" class="chat-gm">
                <div class="gm-line" />
                <div class="gm-text">{{ m.content }}</div>
                <div class="gm-line" />
              </div>
              <div v-else-if="m.role === 'player'" class="chat-row mine">
                <div class="bubble mine-bubble">{{ m.content }}</div>
              </div>
              <div v-else class="chat-row theirs">
                <div class="thr-avatar">{{ (game.npcName(m.speaker_name || '') || '?').slice(0, 1) }}</div>
                <div class="thr-col">
                  <div class="thr-name dim">{{ game.npcName(m.speaker_name || '') }}</div>
                  <div class="bubble theirs-bubble">{{ m.content }}</div>
                </div>
              </div>
            </template>
            <div v-if="game.typing" class="chat-row theirs">
              <div class="thr-avatar">✦</div>
              <div class="thr-col">
                <div class="thr-name dim">主持人</div>
                <div class="bubble theirs-bubble gm-typing">
                  <template v-if="game.partial">
                    {{ game.partial }}<span class="cursor">▍</span>
                  </template>
                  <template v-else>
                    <span class="typing-dot" /><span class="typing-dot" /><span class="typing-dot" />
                  </template>
                </div>
              </div>
            </div>
          </TransitionGroup>
        </div>

        <!-- 输入区 -->
        <div class="chat-input">
          <div v-if="mode === 'question'" class="input-row">
            <span class="input-label dim">向</span>
            <select v-model="selectedTarget" class="select input-compact">
              <option value="" disabled>选择对象…</option>
              <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </div>
          <div v-if="mode === 'introduce_clue'" class="input-row">
            <span class="input-label dim">线索</span>
            <select v-model="selectedClue" class="select input-compact">
              <option value="" disabled>选择要介绍的线索…</option>
              <option v-for="o in clueOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <div class="input-row">
            <input
              v-model="input"
              class="input input-main"
              :placeholder="placeholder || '当前环节无输入'"
              :disabled="game.typing || mode === 'disabled'"
              @keydown.enter="send"
            />
            <button
              class="btn btn-primary"
              :disabled="game.typing || mode === 'disabled' || !input.trim()"
              @click="send"
            >
              {{ mode === 'question' ? '提问' : mode === 'introduce_clue' ? '介绍' : '发送' }}
            </button>
          </div>
          <p v-if="game.error" class="input-error">{{ game.error }}</p>
        </div>
      </main>
    </div>

    <!-- 模态 -->
    <DrawModal :show="showDraw" @close="showDraw = false" />
    <PrivateChatModal
      :show="showPrivate"
      :npc-id="privateNpc"
      @close="showPrivate = false"
      @ended="showPrivate = false"
    />
    <VoteModal :show="showVote" @close="showVote = false" @reveal="openReveal" />
    <RevealModal
      :show="showReveal"
      :reveal="revealData"
      :title="scriptTitle"
      @close="showReveal = false"
      @save="onRevealSave"
      @exit="onRevealExit"
    />
    <CharacterDetailModal
      :show="showCharDetail"
      :char="charDetailChar"
      :card="charDetailCard"
      @close="showCharDetail = false"
    />
    <NotifyModal
      :show="notifyShow"
      :notifications="game.pendingNotifications"
      @close="game.dismissNotifications(); notifyShow = false"
    />
  </div>
</template>

<style scoped>
.game {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.game-top {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 14px 26px;
  border-bottom: 1px solid var(--border);
  background: rgba(11, 11, 15, 0.7);
  backdrop-filter: blur(6px);
  z-index: 5;
}
.top-back {
  background: none;
  border: none;
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 8px;
  transition: all 0.2s;
}
.top-back:hover {
  color: var(--accent-strong);
  background: var(--surface);
}
.top-title {
  flex: 1;
  font-size: 20px;
  letter-spacing: 0.12em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.top-badge {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.badge-act,
.badge-stage {
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 14px;
  letter-spacing: 0.06em;
}
.badge-stage {
  border-color: var(--border-strong);
  background: var(--accent-soft);
}
.game-loading,
.game-error {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 40px;
}
.game-body {
  flex: 1;
  min-height: 0;
  display: flex;
}
/* 左栏 */
.game-left {
  width: 272px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  padding: 18px 16px;
  overflow-y: auto;
}
.left-title {
  font-size: 11px;
  letter-spacing: 0.25em;
  margin-bottom: 10px;
}
.char-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.char-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.25s var(--ease);
}
.char-row:hover {
  background: var(--surface);
  border-color: var(--border);
}
.chr-avatar {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 17px;
  color: var(--accent-strong);
  background: radial-gradient(circle at 30% 25%, var(--surface-3), var(--surface-2));
  border: 1px solid var(--border);
}
.chr-info {
  flex: 1;
  min-width: 0;
}
.chr-name {
  font-size: 13px;
}
.chr-me {
  color: var(--accent);
  font-size: 11px;
  margin-left: 4px;
}
.chr-id {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chr-clues {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 5px;
}
.chr-clue {
  font-size: 10px;
  color: var(--accent-strong);
  background: var(--accent-soft);
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 1px 6px;
}
.chr-private {
  flex-shrink: 0;
}
.chr-private.disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.public-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.public-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}
.public-item:hover {
  border-color: var(--border-strong);
  background: var(--surface-2);
}
.public-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}
.public-empty {
  font-size: 12px;
}
/* 聊天 */
.game-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.chat-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 28px;
}
.chat-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.chat-gm {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 6px 0;
}
.gm-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
}
.gm-text {
  max-width: 70%;
  text-align: center;
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.8;
}
.chat-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
.chat-row.mine {
  justify-content: flex-end;
}
.thr-avatar {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 14px;
  color: var(--accent-strong);
  background: radial-gradient(circle at 30% 25%, var(--surface-3), var(--surface-2));
  border: 1px solid var(--border);
}
.thr-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 70%;
}
.thr-name {
  font-size: 11px;
  margin-left: 2px;
}
.bubble {
  padding: 10px 15px;
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.75;
  word-break: break-word;
}
.mine-bubble {
  background: linear-gradient(135deg, rgba(201, 162, 110, 0.2), rgba(201, 162, 110, 0.08));
  border: 1px solid var(--border-strong);
  border-bottom-right-radius: 4px;
}
.theirs-bubble {
  background: var(--surface);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
}
.gm-typing {
  color: var(--text-2);
  font-style: italic;
}
.cursor {
  color: var(--accent);
  animation: pulse 1s ease-in-out infinite;
}
/* 输入区 */
.chat-input {
  border-top: 1px solid var(--border);
  padding: 14px 22px 18px;
  background: rgba(11, 11, 15, 0.7);
}
.input-row {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}
.input-label {
  font-size: 13px;
  align-self: center;
}
.input-compact {
  width: auto;
  min-width: 180px;
  padding: 8px 14px;
  font-size: 13px;
}
.input-main {
  flex: 1;
}
.input-error {
  color: var(--danger);
  font-size: 12px;
  margin: 8px 0 0;
}
</style>
