<script setup lang="ts">
import { ref, watch } from 'vue'
import api, { type ScriptCard } from '../api'
import { categoryName, textSizeLabel } from '../utils/format'
import AppModal from './AppModal.vue'

const props = defineProps<{
  show: boolean
  scriptId: string
  canAddToLocal?: boolean
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'play', id: string): void; (e: 'added'): void }>()

const loading = ref(false)
const info = ref<ScriptCard | null>(null)
const adding = ref(false)

watch(
  () => [props.show, props.scriptId],
  async ([show]) => {
    if (show && props.scriptId) {
      loading.value = true
      try {
        info.value = await api.getScriptInfo(props.scriptId)
      } catch {
        info.value = null
      } finally {
        loading.value = false
      }
    }
  },
)

async function addToLocal() {
  if (!props.scriptId) return
  adding.value = true
  try {
    await api.saveScript(props.scriptId)
    emit('added')
  } finally {
    adding.value = false
  }
}
</script>

<template>
  <AppModal :show="show" width="460px" @close="emit('close')">
    <div v-if="loading" class="p20">
      <div class="skeleton" style="height: 20px; width: 55%"></div>
      <div class="skeleton" style="height: 14px; width: 100%; margin-top: 18px"></div>
      <div class="skeleton" style="height: 14px; width: 85%; margin-top: 8px"></div>
    </div>
    <div v-else-if="info" class="detail">
      <div class="detail-title display gold">{{ info.title }}</div>
      <div class="detail-tags">
        <span class="tag">{{ categoryName(info.category) }}</span>
        <span class="tag">{{ textSizeLabel(info.text_size) }}</span>
        <span v-if="info.player_count" class="tag">{{ info.player_count }} 人</span>
      </div>
      <p v-if="info.summary" class="detail-summary muted">{{ info.summary }}</p>
      <p v-else class="detail-summary dim">暂无简介。</p>
      <div class="detail-actions">
        <button v-if="canAddToLocal" class="btn btn-sm" :disabled="adding" @click="addToLocal">
          {{ adding ? '加入中…' : '+ 加入本地剧本库' }}
        </button>
        <button class="btn btn-primary" @click="emit('play', info.id)">游玩剧本</button>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.p20 {
  padding: 12px 0;
}
.detail-title {
  font-size: 24px;
  letter-spacing: 0.08em;
}
.detail-tags {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}
.tag {
  font-size: 12px;
  color: var(--text-2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 12px;
  letter-spacing: 0.06em;
}
.detail-summary {
  margin: 18px 0 22px;
  font-size: 14px;
  line-height: 1.8;
  max-height: 120px;
  overflow-y: auto;
}
.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
