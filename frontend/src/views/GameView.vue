<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api, { type CharL1, type CharCard, type Clue, type RevealResult } from '../api'
import { useGameStore } from '../stores/game'
import DrawModal from '../components/DrawModal.vue'
import PrivateChatModal from '../components/PrivateChatModal.vue'
import VoteModal from '../components/VoteModal.vue'
import RevealModal from '../components/RevealModal.vue'
import CharacterDetailModal from '../components/CharacterDetailModal.vue'
import NotifyModal from '../components/NotifyModal.vue'
import AppModal from '../components/AppModal.vue'
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
const revealClue = ref(false)
const showMyClue = ref(false)
const myClueDetail = ref<Clue | null>(null)
const showLeaveConfirm = ref(false)

const input = ref('')
const selectedTarget = ref('')
const selectedClue = ref('')

const chatBody = ref<HTMLElement | null>(null)

/* ---------- 派生 ---------- */

const stage = computed(() => game.stage)

const mode = computed(() => {
  // 讨论阶段：按玩家待办决定输入模式
  if (game.discussion.active) {
    if (game.discussion.playerInput === 'answer') return 'discussion_answer'
    if (game.discussion.playerInput === 'question') return 'discussion_question'
    return 'disabled' // 讨论进行中，还没轮到输入
  }
  const s = stage.value
  if (s === 'intro_r1') return 'introduce'
  if (s === 'intro_r2') return 'question'
  if (s === 'exchange') return game.roundInStage === 0 ? 'introduce_clue' : 'question'
  if (s === 'public') return 'talk'
  if (s === 'draw' || s === 'private' || s === 'vote') return 'disabled'
  return 'talk'
})

const pendingAskerName = computed(() =>
  game.discussion.pendingAsker ? game.npcName(game.discussion.pendingAsker) : '',
)

const targets = computed(() => game.characters.filter((c) => c.id !== game.playerCharId))

const clueOptions = computed(() =>
  game.foundClues.map((c) => ({ value: c.id, label: c.name })),
)

const chatMessages = computed(() =>
  game.messages.filter((m) => m.action_type !== 'private_chat'),
)

const myTarget = computed(() =>
  game.playerCharId ? game.privateSessions[game.playerCharId]?.target : undefined,
)
const sessionClosed = computed(() =>
  game.playerCharId ? game.privateSessions[game.playerCharId]?.closed : false,
)

const publicClues = computed(() => game.publicClues)

const placeholder = computed(() => {
  switch (mode.value) {
    case 'introduce':
      return '自我介绍…'
    case 'introduce_clue':
      return '介绍你拿到的线索，可如实、可隐瞒、可编造…'
    case 'discussion_answer':
      return '回答对方的问题…'
    case 'discussion_question':
      return '提问或发言…（可选公开线索）'
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

/** 点击左侧公开线索：能对应到角色卡才打开（编造陈述无角色卡则忽略）。 */
function openPublicClue(cl: { id: string; name: string }) {
  const ch = findCharOf(cl.id)
  if (ch) openChar(ch)
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
  () => [game.messages.length, game.partial, game.speechTick],
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

function openMyClue(cl: Clue) {
  myClueDetail.value = cl
  showMyClue.value = true
}

function openPrivate(npcId: string) {
  if (!privateEnabled(npcId)) return
  privateNpc.value = npcId
  showPrivate.value = true
}

async function send() {
  const text = input.value.trim()
  if (!text || game.typing || game.speaking || game.discussion.busy) return
  if (mode.value === 'disabled') return

  // 讨论：回答 NPC 的问题 / 自己轮次提问或发言
  if (mode.value === 'discussion_answer') {
    input.value = ''
    await game.discussionAnswer(text)
    return
  }
  if (mode.value === 'discussion_question') {
    const payload2: { target?: string; clueId?: string; reveal?: boolean } = {}
    if (selectedTarget.value) payload2.target = selectedTarget.value
    if (selectedClue.value) {
      payload2.clueId = selectedClue.value
      payload2.reveal = revealClue.value
    }
    input.value = ''
    selectedTarget.value = ''
    selectedClue.value = ''
    revealClue.value = false
    await game.discussionAction(text, payload2.target, payload2.clueId, payload2.reveal)
    return
  }

  const payload: {
    action: string
    action_type: string
    actor_id: string
    target_id: string | null
    clue_id: string | null
    reveal: boolean
  } = {
    action: text,
    action_type: mode.value,
    actor_id: game.playerCharId || 'player',
    target_id: null,
    clue_id: null,
    reveal: false,
  }

  if (mode.value === 'question') {
    if (!selectedTarget.value) {
      toast('请先选择提问对象', 'error')
      return
    }
    payload.target_id = selectedTarget.value
  }

  if (mode.value === 'introduce_clue') {
    if (!selectedClue.value) {
      toast('请先选择要介绍的线索', 'error')
      return
    }
    payload.clue_id = selectedClue.value
    payload.reveal = revealClue.value
    const c = game.foundClues.find((x) => x.id === selectedClue.value)
    payload.action = text || c?.name || text
  }

  input.value = ''
  selectedTarget.value = ''
  selectedClue.value = ''
  revealClue.value = false
  await game.sendAction(payload)
}

/** 讨论：玩家跳过本轮提问（其他 NPC 该轮照常提问）。 */
async function skipDiscussion() {
  if (game.discussion.busy) return
  await game.discussionPass()
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
  showLeaveConfirm.value = true
}
function confirmLeave() {
  showLeaveConfirm.value = false
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
            @click="openPublicClue(cl)"
          >
            <span class="public-dot" />
            {{ cl.name }}
          </button>
        </div>
        <p v-else class="public-empty dim">搜证与交换信息后，公开线索会出现在这里</p>

        <div class="left-title dim" style="margin-top: 20px">我的线索</div>
        <div v-if="game.foundClues.length" class="public-list">
          <button
            v-for="cl in game.foundClues"
            :key="cl.id"
            class="public-item mine-item"
            @click="openMyClue(cl)"
          >
            <span class="public-dot mine-dot" />
            {{ cl.name }}
          </button>
        </div>
        <p v-else class="public-empty dim">抽卡搜证后，你抽到的线索会出现在这里</p>
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
                  <div class="bubble theirs-bubble">
                    {{ m.content }}<span v-if="m.__sid === game.typingSpeechSid" class="cursor">▍</span>
                  </div>
                </div>
              </div>
            </template>
            <!-- GM 生成中：居中等待提示（非气泡），完成后整段淡入 -->
            <div v-if="game.typing" class="gm-waiting">
              <span class="gm-line" />
              <span class="gm-wait-text">主持人…</span>
              <span class="gm-line" />
            </div>
          </TransitionGroup>
        </div>

        <!-- 输入区 -->
        <div class="chat-input">
          <!-- 讨论横幅 -->
          <div v-if="game.discussion.active" class="disc-banner">
            <span class="disc-badge">讨论 · 第 {{ game.discussion.round }}/{{ game.discussion.maxRounds }} 轮</span>
            <span v-if="mode === 'discussion_answer'" class="disc-prompt">
              {{ pendingAskerName }} 在问你：{{ game.discussion.pendingQuestion }}
            </span>
            <span v-else-if="mode === 'discussion_question'" class="disc-prompt">
              轮到你了——提问或发言，可公开自己的线索，也可跳过
            </span>
            <span v-else class="disc-prompt dim">讨论进行中…</span>
          </div>

          <div v-if="mode === 'discussion_question' || mode === 'discussion_answer'" class="input-row">
            <span class="input-label dim">向</span>
            <select v-model="selectedTarget" class="select input-compact">
              <option value="" disabled>选择对象（可选）</option>
              <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </div>
          <div v-if="mode === 'discussion_question'" class="input-row">
            <span class="input-label dim">线索</span>
            <select v-model="selectedClue" class="select input-compact">
              <option value="" disabled>选择要公开的线索（可选）</option>
              <option v-for="o in clueOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <label v-if="mode === 'discussion_question' && selectedClue" class="reveal-toggle">
            <input v-model="revealClue" type="checkbox" />
            <span>如实介绍（公开这条线索的真实内容）</span>
          </label>
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
          <label v-if="mode === 'introduce_clue'" class="reveal-toggle">
            <input v-model="revealClue" type="checkbox" />
            <span>如实介绍（公开这条线索的真实内容）</span>
          </label>
          <div class="input-row">
            <input
              v-model="input"
              class="input input-main"
              :placeholder="placeholder || '当前环节无输入'"
              :disabled="game.typing || game.speaking || game.discussion.busy || mode === 'disabled'"
              @keydown.enter="send"
            />
            <button
              v-if="mode === 'discussion_question'"
              class="btn btn-ghost"
              :disabled="game.typing || game.speaking || game.discussion.busy"
              @click="skipDiscussion"
            >
              跳过
            </button>
            <button
              class="btn btn-primary"
              :disabled="game.typing || game.speaking || game.discussion.busy || mode === 'disabled' || !input.trim()"
              @click="send"
            >
              {{
                mode === 'discussion_answer'
                  ? '回答'
                  : mode === 'discussion_question'
                    ? '发言'
                    : mode === 'question'
                      ? '提问'
                      : mode === 'introduce_clue'
                        ? '介绍'
                        : '发送'
              }}
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
    <AppModal :show="showMyClue" width="440px" @close="showMyClue = false">
      <div v-if="myClueDetail">
        <div class="mc-name display gold">{{ myClueDetail.name }}</div>
        <p class="mc-desc">{{ myClueDetail.description }}</p>
        <div v-if="myClueDetail.location" class="mc-loc dim">来源地点：{{ myClueDetail.location }}</div>
        <button class="btn btn-primary mc-btn" @click="showMyClue = false">关闭</button>
      </div>
    </AppModal>
    <AppModal :show="showLeaveConfirm" width="380px" @close="showLeaveConfirm = false">
      <div class="leave-confirm-head display gold">返回剧本库</div>
      <p class="leave-confirm-text">当前对局尚未结束，返回剧本库后将退出本局游戏。确定返回吗？</p>
      <div class="leave-confirm-actions">
        <button class="btn btn-ghost" @click="showLeaveConfirm = false">取消</button>
        <button class="btn btn-primary" @click="confirmLeave">确认返回</button>
      </div>
    </AppModal>
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
.mine-item {
  border-style: dashed;
}
.mine-item:hover {
  border-style: dashed;
  border-color: var(--accent-strong);
}
.mine-dot {
  background: var(--accent-strong);
}
.public-empty {
  font-size: 12px;
}
.reveal-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  margin: 2px 0 10px;
  user-select: none;
}
.reveal-toggle input {
  accent-color: var(--accent-strong);
  cursor: pointer;
}
.mc-name {
  font-size: 20px;
  margin-bottom: 10px;
}
.mc-desc {
  font-size: 13px;
  line-height: 1.8;
  color: var(--text);
  margin: 0;
}
.mc-loc {
  font-size: 12px;
  margin-top: 12px;
}
.mc-btn {
  margin-top: 22px;
  width: 100%;
}
.leave-confirm-head {
  font-size: 19px;
  margin-bottom: 12px;
}
.leave-confirm-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.8;
  color: var(--text);
}
.leave-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 26px;
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
.cursor {
  color: var(--accent);
  animation: pulse 1s ease-in-out infinite;
}
/* GM 生成中的居中等待提示 */
.gm-waiting {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 10px 0;
}
.gm-wait-text {
  font-size: 12px;
  color: var(--text-3);
  letter-spacing: 0.2em;
  animation: gmWaitPulse 1.6s ease-in-out infinite;
}
@keyframes gmWaitPulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}
/* GM 旁白/自发言统一淡入 */
.gm-text {
  animation: gmFadeIn 1.1s var(--ease);
}
@keyframes gmFadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
    filter: blur(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
    filter: blur(0);
  }
}
/* 输入区 */
.chat-input {
  border-top: 1px solid var(--border);
  padding: 14px 22px 18px;
  background: rgba(11, 11, 15, 0.7);
}
/* 讨论横幅 */
.disc-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
  padding: 8px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  background: var(--accent-soft);
}
.disc-badge {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--accent-strong);
  border: 1px solid var(--border-strong);
  border-radius: 20px;
  padding: 2px 12px;
  letter-spacing: 0.05em;
}
.disc-prompt {
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
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
