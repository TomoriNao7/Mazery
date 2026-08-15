<script setup lang="ts">
import type { ScriptCard } from '../api'
import BookCard from './BookCard.vue'

defineProps<{ scripts: ScriptCard[]; emptyText: string }>()
const emit = defineEmits<{ (e: 'open', s: ScriptCard): void }>()
</script>

<template>
  <div v-if="scripts.length" class="shelf-grid">
    <div
      v-for="(s, i) in scripts"
      :key="s.id"
      class="shelf-item"
      :style="{ animationDelay: i * 45 + 'ms' }"
      @click="emit('open', s)"
    >
      <BookCard :script="s" />
    </div>
  </div>
  <div v-else class="shelf-empty anim-fade">
    <div class="shelf-empty-icon">◌</div>
    <p class="muted">{{ emptyText }}</p>
  </div>
</template>

<style scoped>
.shelf-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 30px 26px;
}
.shelf-item {
  animation: fadeUp 0.5s var(--ease) both;
}
.shelf-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 90px 0;
}
.shelf-empty-icon {
  font-size: 40px;
  opacity: 0.4;
  margin-bottom: 14px;
}
</style>
