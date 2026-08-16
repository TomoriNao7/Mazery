<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import api, { type GameMessage } from '../api'
import { useGameStore } from '../stores/game'
import AppModal from './AppModal.vue'

const props = defineProps<{ show: boolean; npcId: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'ended'): void }>()

const game = useGameStore()
const messages = ref<GameMessage[]>([])
const input = ref('')
const sending = ref(false)
const ending = ref(false)

const npcName = computed(() => game.npcName(props.npcId))
const mySession = computed(() =>
  game.playerCharId ? game.privateSessions[game.playerCharId] : undefined,
)
const count = computed(() => mySession.value?.count ?? 0)
const max = 32
const remaining = computed(() => Math.max(0, max - count.value))

async function load() {
  messages.value = []
  if (!props.show) return
  try {
    const msgs = await api.getPrivateHistory(game.gameId, props.npcId)
    messages.value = msgs
  } catch {
    /* ignore */
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  const local = text
  input.value = ''
  messages.value.push({ role: 'player', speaker_name: game.playerCharId, content: local })
  const replyMsg = {
    role: `character_${props.npcId}`,
    speaker_name: props.npcId,
    content: '',
    action_type: 'private_chat',
  }
  messages.value.push(replyMsg)
  try {
    const res = await game.sendPrivate(props.npcId, local, (t) => {
      replyMsg.content += t
    })
    if (!res.npc_reply) replyMsg.content = '……（对方似乎不愿多说）'
    if (res.forced_end) {
      setTimeout(() => emit('ended'), 600)
    }
  } catch (e) {
    // 发送失败：移除空回复气泡，恢复输入
    messages.value.pop()
    input.value = local
  } finally {
    sending.value = false
  }
}

async function end() {
  if (ending.value) return
  ending.value = true
  try {
    const res = await game.endPrivate(props.npcId)
    if (res.transition) emit('ended')
    else emit('close')
  } catch {
    emit('close')
  } finally {
    ending.value = false
  }
}

watch(
  () => [props.show, props.npcId],
  () => void load(),
)
</script>

<template>
  <AppModal :show="show" width="520px" @close="emit('close')">
    <div class="pc">
      <div class="pc-head">
        <div class="pc-avatar">{{ (npcName || '?').slice(0, 1) }}</div>
        <div class="pc-name display gold">{{ npcName }}</div>
        <div class="pc-count dim">
          {{ count }}/{{ max }} · 剩余 {{ remaining }}
        </div>
      </div>

      <div class="pc-body">
        <div v-if="!messages.length" class="pc-empty dim">
          私聊开始 —— 对方可能更坦诚，也可能在说谎。
        </div>
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="pc-msg"
          :class="m.role === 'player' ? 'mine' : 'theirs'"
        >
          <div class="pc-bubble">{{ m.content }}</div>
        </div>
      </div>

      <div class="pc-input">
        <input
          v-model="input"
          class="input"
          placeholder="说点什么…"
          :disabled="sending || remaining <= 0"
          @keydown.enter="send"
        />
        <button class="btn btn-primary" :disabled="sending || remaining <= 0 || !input.trim()" @click="send">
          发送
        </button>
      </div>
      <div class="pc-foot">
        <button class="btn btn-ghost btn-sm" :disabled="ending" @click="end">
          {{ remaining > 0 ? '结束私聊' : '已达上限，即将结束' }}
        </button>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.pc {
  display: flex;
  flex-direction: column;
  height: 460px;
}
.pc-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.pc-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--accent-strong);
  background: radial-gradient(circle at 30% 25%, var(--surface-3), var(--surface-2));
  border: 1px solid var(--border-strong);
}
.pc-name {
  font-size: 17px;
  flex: 1;
}
.pc-count {
  font-size: 12px;
}
.pc-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 4px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.pc-empty {
  text-align: center;
  font-size: 12px;
  padding: 30px 0;
}
.pc-msg {
  display: flex;
}
.pc-msg.mine {
  justify-content: flex-end;
}
.pc-msg.theirs {
  justify-content: flex-start;
}
.pc-bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.7;
  animation: fadeUp 0.35s var(--ease) both;
}
.mine .pc-bubble {
  background: linear-gradient(135deg, rgba(201, 162, 110, 0.2), rgba(201, 162, 110, 0.08));
  border: 1px solid var(--border-strong);
  border-bottom-right-radius: 4px;
  color: var(--text);
}
.theirs .pc-bubble {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  color: var(--text);
}
.pc-input {
  display: flex;
  gap: 10px;
  padding-top: 12px;
}
.pc-foot {
  display: flex;
  justify-content: center;
  margin-top: 10px;
}
</style>
