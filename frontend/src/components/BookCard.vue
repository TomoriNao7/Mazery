<script setup lang="ts">
import type { ScriptCard } from '../api'
import { categoryName, textSizeLabel } from '../utils/format'

defineProps<{ script: ScriptCard }>()
</script>

<template>
  <div class="book">
    <div class="book-cover">
      <div class="book-spine" />
      <div class="book-face">
        <div class="book-title display">{{ script.title }}</div>
        <div class="book-rule" />
        <div class="book-cat dim">{{ categoryName(script.category) }}</div>
      </div>
      <div class="book-gloss" />
    </div>
    <div class="book-meta">
      <span class="muted">{{ categoryName(script.category) }}</span>
      <span class="dot" />
      <span class="dim">{{ textSizeLabel(script.text_size) }}</span>
    </div>
  </div>
</template>

<style scoped>
.book {
  width: 100%;
  cursor: pointer;
}
.book-cover {
  position: relative;
  height: 176px;
  border-radius: 6px 10px 10px 6px;
  background: linear-gradient(150deg, #23232e 0%, #1a1a22 55%, #15151b 100%);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-1);
  overflow: hidden;
  transition: transform 0.35s var(--ease), box-shadow 0.35s var(--ease),
    border-color 0.35s var(--ease);
}
.book:hover .book-cover {
  transform: translateY(-4px);
  border-color: var(--border-strong);
  box-shadow: var(--shadow-gold);
}
.book-spine {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 10px;
  background: linear-gradient(90deg, rgba(201, 162, 110, 0.28), rgba(201, 162, 110, 0.05));
  border-right: 1px solid rgba(255, 255, 255, 0.05);
}
.book-face {
  position: absolute;
  inset: 0 0 0 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 12px;
  text-align: center;
}
.book-title {
  font-size: 17px;
  line-height: 1.35;
  color: var(--text);
  letter-spacing: 0.06em;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.book-rule {
  width: 40px;
  height: 1px;
  margin: 10px 0 8px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
}
.book-cat {
  font-size: 12px;
  letter-spacing: 0.18em;
}
.book-gloss {
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 42%, rgba(255, 255, 255, 0.05) 50%, transparent 58%);
}
.book-meta {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 12px;
  letter-spacing: 0.04em;
}
.dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-3);
}
</style>
