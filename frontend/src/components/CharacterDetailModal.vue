<script setup lang="ts">
import type { CharL1, CharCard } from '../api'
import AppModal from './AppModal.vue'

defineProps<{ show: boolean; char: CharL1 | null; card?: CharCard | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <AppModal :show="show" width="440px" @close="emit('close')">
    <div v-if="char" class="cd">
      <div class="cd-head">
        <div class="cd-avatar">{{ (char.name || '?').slice(0, 1) }}</div>
        <div>
          <div class="cd-name display gold">{{ char.name }}</div>
          <div class="cd-identity muted">{{ char.identity || char.profession || '身份未知' }}</div>
        </div>
      </div>
      <div v-if="char.appearance" class="cd-block">
        <div class="cd-label dim">外貌</div>
        <p class="cd-text">{{ char.appearance }}</p>
      </div>
      <div v-if="char.personality" class="cd-block">
        <div class="cd-label dim">个性</div>
        <p class="cd-text">{{ char.personality }}</p>
      </div>
      <div v-if="char.background" class="cd-block">
        <div class="cd-label dim">公开背景</div>
        <p class="cd-text">{{ char.background }}</p>
      </div>

      <div v-if="card && card.clues && card.clues.length" class="cd-block">
        <div class="cd-label dim">已写入该人物的线索</div>
        <div class="clue-list">
          <div v-for="c in card.clues" :key="c.id" class="clue-item">
            <div class="clue-name gold">{{ c.name }}</div>
            <p class="clue-desc">{{ c.description }}</p>
          </div>
        </div>
      </div>
      <p v-else class="dim no-clue">该人物暂无公开线索。</p>
    </div>
  </AppModal>
</template>

<style scoped>
.cd-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}
.cd-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 24px;
  color: var(--accent-strong);
  background: radial-gradient(circle at 30% 25%, var(--surface-3), var(--surface-2));
  border: 1px solid var(--border-strong);
}
.cd-name {
  font-size: 20px;
}
.cd-identity {
  font-size: 13px;
  margin-top: 2px;
}
.cd-block {
  margin-top: 13px;
}
.cd-label {
  font-size: 11px;
  letter-spacing: 0.2em;
  margin-bottom: 5px;
}
.cd-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
}
.clue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.clue-item {
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}
.clue-name {
  font-size: 13px;
  letter-spacing: 0.04em;
}
.clue-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.7;
}
.no-clue {
  font-size: 12px;
  margin-top: 12px;
}
</style>
