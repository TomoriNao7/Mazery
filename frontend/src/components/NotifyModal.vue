<script setup lang="ts">
import AppModal from './AppModal.vue'

defineProps<{ show: boolean; notifications: string[] }>()
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <AppModal :show="show" width="400px" title="剧情更新">
    <div class="ntf">
      <div class="ntf-orn">✦</div>
      <ul class="ntf-list">
        <li v-for="(n, i) in notifications" :key="i" class="ntf-item anim-fade-up">
          {{ n }}
        </li>
      </ul>
      <button class="btn btn-primary ntf-btn" @click="emit('close')">知道了</button>
    </div>
  </AppModal>
</template>

<style scoped>
.ntf {
  text-align: center;
  padding: 6px 0 2px;
}
.ntf-orn {
  color: var(--accent);
  font-size: 20px;
  margin-bottom: 12px;
  animation: pulse 2s ease-in-out infinite;
}
.ntf-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  text-align: left;
}
.ntf-item {
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-left: 2px solid var(--accent);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text);
}
.ntf-btn {
  margin-top: 22px;
}
</style>
