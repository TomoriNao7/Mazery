<script setup lang="ts">
import { ref, watch } from 'vue'
import { useGameStore } from '../stores/game'
import AppModal from './AppModal.vue'
import type { VoteResult } from '../api'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'reveal'): void }>()

const game = useGameStore()
const selected = ref('')
const phase = ref<'vote' | 'result'>('vote')
const result = ref<VoteResult | null>(null)
const voting = ref(false)
const error = ref('')

async function submit() {
  if (!selected.value || voting.value) return
  voting.value = true
  error.value = ''
  try {
    result.value = await game.voteNow(selected.value)
    phase.value = 'result'
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    voting.value = false
  }
}

function reset() {
  selected.value = ''
  phase.value = 'vote'
  result.value = null
  error.value = ''
}

watch(
  () => props.show,
  (v) => {
    if (v) reset()
  },
)
</script>

<template>
  <AppModal :show="show" width="520px" title="投票指认凶手" @close="emit('close')">
    <div v-if="phase === 'vote'" class="vote">
      <p class="vote-hint dim">所有人将依次指认自己认为的凶手 —— 请选择你的指认对象</p>
      <div class="vote-list">
        <button
          v-for="c in game.characters"
          :key="c.id"
          class="vote-item card card-hover"
          :class="{ on: selected === c.id }"
          @click="selected = c.id"
        >
          <span class="vote-avatar">{{ (c.name || '?').slice(0, 1) }}</span>
          <span class="vote-name">{{ c.name }}</span>
          <span class="vote-mark" />
        </button>
      </div>
      <p v-if="error" class="vote-error">{{ error }}</p>
      <div class="vote-actions">
        <button class="btn btn-primary" :disabled="!selected || voting" @click="submit">
          {{ voting ? '投票中…' : '确认指认' }}
        </button>
      </div>
    </div>

    <div v-else-if="result" class="result">
      <p class="result-title dim">你的指认</p>
      <div class="result-pick">{{ game.npcName(selected) }}</div>
      <p class="result-title dim" style="margin-top: 18px">全角色投票汇总</p>
      <div class="result-counts">
        <div v-for="(n, id) in result.vote_counts" :key="id" class="rc">
          <span class="rc-name">{{ game.npcName(id) }}</span>
          <div class="rc-bar"><div class="rc-fill" :style="{ width: (n / game.characters.length) * 100 + '%' }" /></div>
          <span class="rc-n">{{ n }} 票</span>
        </div>
      </div>
      <div class="vote-actions">
        <button class="btn btn-primary" @click="emit('reveal')">查看 GM 复盘</button>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.vote-hint {
  font-size: 13px;
  margin: 0 0 18px;
}
.vote-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 12px;
}
.vote-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px 10px;
  border: none;
  color: var(--text);
  cursor: pointer;
  background: var(--surface);
  position: relative;
}
.vote-item.on {
  border-color: var(--border-strong);
  background: var(--accent-soft);
  box-shadow: var(--shadow-gold);
}
.vote-avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--accent-strong);
  background: radial-gradient(circle at 30% 25%, var(--surface-3), var(--surface-2));
  border: 1px solid var(--border);
}
.vote-name {
  font-size: 13px;
}
.vote-mark {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 1px solid var(--border);
}
.vote-item.on .vote-mark {
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent);
}
.vote-error {
  color: var(--danger);
  font-size: 12px;
  margin: 14px 0 0;
}
.vote-actions {
  display: flex;
  justify-content: center;
  margin-top: 22px;
}
.result-title {
  font-size: 12px;
  letter-spacing: 0.2em;
  margin: 0 0 8px;
}
.result-pick {
  font-size: 22px;
  color: var(--accent-strong);
  font-family: var(--font-display);
  letter-spacing: 0.06em;
}
.result-counts {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}
.rc {
  display: flex;
  align-items: center;
  gap: 12px;
}
.rc-name {
  width: 90px;
  font-size: 13px;
  text-align: right;
}
.rc-bar {
  flex: 1;
  height: 8px;
  background: var(--surface-2);
  border-radius: 6px;
  overflow: hidden;
}
.rc-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-dim), var(--accent-strong));
  border-radius: 6px;
  transition: width 0.6s var(--ease);
}
.rc-n {
  width: 40px;
  font-size: 12px;
  color: var(--text-2);
}
</style>
