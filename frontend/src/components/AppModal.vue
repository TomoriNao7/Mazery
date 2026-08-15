<script setup lang="ts">
withDefaults(
  defineProps<{
    show: boolean
    width?: string
    title?: string
  }>(),
  { width: '480px', title: '' },
)
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <teleport to="body">
    <Transition name="fade">
      <div v-if="show" class="modal-mask" @click.self="emit('close')">
        <div class="modal-body" :style="{ width, maxWidth: '92vw' }">
          <div v-if="title" class="modal-head">
            <span class="display gold" style="font-size: 18px">{{ title }}</span>
            <button class="modal-x" @click="emit('close')">✕</button>
          </div>
          <slot />
        </div>
      </div>
    </Transition>
  </teleport>
</template>

<style scoped>
.modal-body {
  background: linear-gradient(180deg, #1b1b24, #13131a);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-gold);
  padding: 24px;
  max-height: 86vh;
  overflow-y: auto;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.modal-x {
  background: none;
  border: none;
  color: var(--text-3);
  font-size: 15px;
  cursor: pointer;
  padding: 4px 9px;
  border-radius: 6px;
  transition: all 0.2s;
}
.modal-x:hover {
  color: var(--text);
  background: var(--surface-2);
}
</style>
