<script setup lang="ts">
import { toasts } from '../utils/toast'
</script>

<template>
  <teleport to="body">
    <div class="toast-host">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
          <span class="toast-dot" />
          {{ t.text }}
        </div>
      </TransitionGroup>
    </div>
  </teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: 22px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 300;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 20px;
  border-radius: 12px;
  background: linear-gradient(180deg, #1f1f29, #17171f);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-2);
  font-size: 13px;
  color: var(--text);
}
.toast-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.toast.info .toast-dot {
  background: var(--accent);
}
.toast.success .toast-dot {
  background: var(--ok);
}
.toast.error .toast-dot {
  background: var(--danger);
}
.toast-enter-active,
.toast-leave-active {
  transition: all 0.35s var(--ease);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}
</style>
