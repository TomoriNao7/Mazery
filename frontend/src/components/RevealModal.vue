<script setup lang="ts">
import type { RevealResult } from '../api'
import AppModal from './AppModal.vue'

defineProps<{ show: boolean; reveal: RevealResult | null; title?: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'save'): void; (e: 'exit'): void }>()

function describe(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'object') {
    const parts = Object.entries(v as Record<string, unknown>).map(([k, val]) =>
      typeof val === 'string' || typeof val === 'number' ? `${k}: ${val}` : k,
    )
    return parts.join('；')
  }
  return String(v)
}
</script>

<template>
  <AppModal :show="show" width="600px" @close="emit('close')">
    <div v-if="reveal" class="rv">
      <div class="rv-head">
        <div class="rv-badge display gold">真相揭晓</div>
        <div v-if="reveal.grade" class="rv-grade">{{ reveal.grade }}</div>
      </div>
      <div class="rv-title display">{{ title || '迷局揭晓' }}</div>

      <div v-if="reveal.truth_summary" class="rv-block">
        <div class="rv-label dim">真相</div>
        <p class="rv-text">{{ reveal.truth_summary }}</p>
      </div>

      <div v-if="reveal.missed_details?.length" class="rv-block">
        <div class="rv-label dim">你可能错过的细节</div>
        <ul class="rv-list">
          <li v-for="(m, i) in reveal.missed_details" :key="i">{{ describe(m) }}</li>
        </ul>
      </div>

      <div v-if="reveal.npc_outcomes?.length" class="rv-block">
        <div class="rv-label dim">人物结局</div>
        <ul class="rv-list">
          <li v-for="(o, i) in reveal.npc_outcomes" :key="i">{{ describe(o) }}</li>
        </ul>
      </div>

      <div v-if="reveal.player_score" class="rv-block rv-score">
        <div class="rv-label dim">本局评分</div>
        <div class="rv-score-total">{{ reveal.player_score.total ?? '—' }}</div>
        <p v-if="reveal.player_score.breakdown?.length" class="rv-text dim" style="font-size: 12px">
          {{ reveal.player_score.breakdown.map(describe).join('；') }}
        </p>
      </div>

      <div class="rv-actions">
        <button class="btn btn-primary" @click="emit('save')">保存该剧本到剧本库</button>
        <button class="btn btn-ghost" @click="emit('exit')">直接退出</button>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.rv {
  padding: 4px 0;
}
.rv-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.rv-badge {
  font-size: 14px;
  letter-spacing: 0.4em;
}
.rv-grade {
  font-family: var(--font-display);
  font-size: 46px;
  color: var(--accent-strong);
  text-shadow: 0 0 24px rgba(201, 162, 110, 0.4);
}
.rv-title {
  font-size: 26px;
  margin: 8px 0 18px;
  letter-spacing: 0.1em;
}
.rv-block {
  margin-top: 16px;
}
.rv-label {
  font-size: 11px;
  letter-spacing: 0.25em;
  margin-bottom: 7px;
}
.rv-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.9;
}
.rv-list {
  margin: 0;
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rv-list li {
  font-size: 13px;
  line-height: 1.8;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 13px;
}
.rv-score {
  text-align: center;
  padding: 10px 0 4px;
}
.rv-score-total {
  font-family: var(--font-display);
  font-size: 38px;
  color: var(--accent-strong);
}
.rv-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 26px;
}
</style>
